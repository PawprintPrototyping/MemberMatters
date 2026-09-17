"""Provider-aware induction requirement evaluation and verification."""

from dataclasses import dataclass
from datetime import timedelta

from constance import config
from django.db import transaction
from django.utils import timezone
from sentry_sdk import capture_exception

from services.canvas import Canvas
from services.docuseal import (
    create_submission_for_subscription,
    get_docuseal_submission,
    submission_is_complete,
    submission_is_declined,
)
from services.moodle_integration import (
    moodle_get_course_activity_completion_status,
    moodle_get_user_from_email,
)


@dataclass(frozen=True)
class InductionRequirement:
    provider: str
    requirement_key: str
    action_url: str


def enabled_requirements():
    """Return every induction provider enabled by the current configuration."""
    requirements = []
    if config.CANVAS_INDUCTION_ENABLED:
        requirements.append(
            InductionRequirement(
                provider="canvas",
                requirement_key=(
                    f"canvas:course:{config.CANVAS_INDUCTION_COURSE_ID}:"
                    f"minimum-score:{config.MIN_INDUCTION_SCORE}"
                ),
                action_url=config.INDUCTION_ENROL_LINK,
            )
        )
    if config.MOODLE_INDUCTION_ENABLED:
        requirements.append(
            InductionRequirement(
                provider="moodle",
                requirement_key=(
                    f"moodle:course:{config.MOODLE_INDUCTION_COURSE_ID}:"
                    f"minimum-score:{config.MIN_INDUCTION_SCORE}"
                ),
                action_url=config.INDUCTION_ENROL_LINK,
            )
        )
    if config.ENABLE_DOCUSEAL_INTEGRATION:
        requirements.append(
            InductionRequirement(
                provider="docuseal",
                requirement_key=f"docuseal:template:{config.DOCUSEAL_TEMPLATE_ID}",
                action_url="",
            )
        )
    return requirements


def _is_current_completion(state, now):
    if not (state and state.status == "complete" and state.completed_at):
        return False
    if config.MAX_INDUCTION_DAYS <= 0:
        return True
    return state.completed_at >= now - timedelta(days=config.MAX_INDUCTION_DAYS)


def get_status(profile, states=None):
    """Return local, authorization-safe status for each enabled provider."""
    now = timezone.now()
    if states is None:
        prefetched = getattr(profile, "_prefetched_objects_cache", {}).get(
            "induction_provider_states"
        )
        states = (
            prefetched
            if prefetched is not None
            else list(profile.induction_provider_states.all())
        )
    state_by_requirement = {
        (state.provider, state.requirement_key): state for state in states
    }
    legacy_state = state_by_requirement.get(("legacy", "legacy:last-induction"))
    moodle_enabled = any(
        requirement.provider == "moodle" for requirement in enabled_requirements()
    )
    providers = []

    for requirement in enabled_requirements():
        state = state_by_requirement.get(
            (requirement.provider, requirement.requirement_key)
        )
        # The former aggregate timestamp had no course or provider identity.
        # It can satisfy the provider the old flow would have checked: Moodle
        # when enabled, otherwise Canvas. It never proves Docuseal signing and
        # never overrides a concrete requirement-local state.
        if state is None and legacy_state:
            if requirement.provider == "moodle" or (
                requirement.provider == "canvas" and not moodle_enabled
            ):
                state = legacy_state
        is_complete = _is_current_completion(state, now)
        status = "complete" if is_complete else (state.status if state else "pending")
        error_code = "" if is_complete or not state else state.error_code
        if state and state.status == "complete" and not is_complete:
            status = "pending"
            error_code = "reverificationRequired"

        action_url = (
            profile.memberdoc_url
            if requirement.provider == "docuseal"
            else requirement.action_url
        )
        providers.append(
            {
                "provider": requirement.provider,
                "status": status,
                "complete": is_complete,
                "score": state.score if state else None,
                "errorCode": error_code,
                "actionUrl": action_url,
                "completedAt": state.completed_at if is_complete else None,
                "checkedAt": state.checked_at if state else None,
            }
        )

    return {
        "complete": all(item["complete"] for item in providers),
        "providers": providers,
    }


def _passes_score(score):
    return score is not None and score >= config.MIN_INDUCTION_SCORE


def _verify_canvas(profile):
    try:
        score = Canvas().get_student_score_for_course(
            config.CANVAS_INDUCTION_COURSE_ID, profile.user.email
        )
        score = 0 if score is None else int(score)
        if _passes_score(score) or config.MIN_INDUCTION_SCORE == 0:
            return "complete", score, ""
        return "pending", score, "canvasPending"
    except Exception as error:
        capture_exception(error)
        return "unavailable", None, "canvasUnavailable"


def _verify_moodle(profile):
    try:
        moodle_user = moodle_get_user_from_email(profile.user.email)
        activities = moodle_get_course_activity_completion_status(
            config.MOODLE_INDUCTION_COURSE_ID, moodle_user["id"]
        )
        score = activities["percentage_completed"]
        if _passes_score(score) or config.MIN_INDUCTION_SCORE == 0:
            return "complete", score, ""
        return "pending", score, "moodlePending"
    except RuntimeError:
        # The Moodle adapter uses RuntimeError for no/ambiguous account matches.
        return "pending", None, "noMoodleAccount"
    except Exception as error:
        capture_exception(error)
        return "unavailable", None, "moodleUnavailable"


def _reserve_docuseal_submission(profile_id, requirement):
    """Return one durable DocuSeal submission reservation for a requirement.

    The profile lock intentionally covers submission creation. It prevents two
    browser tabs from issuing duplicate agreements before either can persist
    the external submission id for this requirement.
    """
    from profile.models import InductionProviderState, Profile

    with transaction.atomic():
        profile = Profile.objects.select_for_update().get(pk=profile_id)
        state, _ = InductionProviderState.objects.get_or_create(
            profile=profile,
            provider="docuseal",
            requirement_key=requirement.requirement_key,
            defaults={"status": "pending"},
        )
        if state.external_reference:
            return profile, state

        prior_requirement_exists = (
            InductionProviderState.objects.filter(profile=profile, provider="docuseal")
            .exclude(requirement_key=requirement.requirement_key)
            .exists()
        )
        if profile.memberdoc_id and not prior_requirement_exists:
            # A submission created before provider state was introduced belongs
            # to the first requirement seen after rollout.
            state.external_reference = str(profile.memberdoc_id)
        else:
            create_submission_for_subscription(profile)
            if not profile.memberdoc_id:
                raise RuntimeError("DocuSeal did not return a submission id")
            state.external_reference = str(profile.memberdoc_id)
        state.save(update_fields=["external_reference"])
        return profile, state


def _verify_docuseal(profile, state):
    if not state.external_reference:
        return "pending", None, "docusealPending"
    try:
        submission = get_docuseal_submission(profile, state.external_reference)
        if submission_is_complete(submission):
            return "complete", None, ""
        if submission_is_declined(submission):
            return "declined", None, "docusealDeclined"
        return "pending", None, "docusealPending"
    except Exception as error:
        capture_exception(error)
        return "unavailable", None, "docusealUnavailable"


def _verify(profile, provider):
    if provider == "canvas":
        return _verify_canvas(profile)
    if provider == "moodle":
        return _verify_moodle(profile)
    raise ValueError(f"Unsupported induction provider: {provider}")


def _save_verification(state, provider_status, score, error_code, now):
    state.status = provider_status
    state.checked_at = now
    state.score = score
    state.error_code = error_code
    state.completed_at = now if provider_status == "complete" else None
    state.save(
        update_fields=["status", "checked_at", "score", "error_code", "completed_at"]
    )


def refresh(profile):
    """Verify and persist the state of every provider enabled right now."""
    from profile.models import InductionProviderState, Profile

    now = timezone.now()
    for requirement in enabled_requirements():
        if requirement.provider == "docuseal":
            try:
                verification_profile, state = _reserve_docuseal_submission(
                    profile.pk, requirement
                )
                provider_status, score, error_code = _verify_docuseal(
                    verification_profile, state
                )
            except Exception as error:
                capture_exception(error)
                state, _ = InductionProviderState.objects.get_or_create(
                    profile_id=profile.pk,
                    provider="docuseal",
                    requirement_key=requirement.requirement_key,
                    defaults={"external_reference": ""},
                )
                provider_status, score, error_code = (
                    "unavailable",
                    None,
                    "docusealUnavailable",
                )
        else:
            provider_status, score, error_code = _verify(profile, requirement.provider)
            state, _ = InductionProviderState.objects.get_or_create(
                profile_id=profile.pk,
                provider=requirement.provider,
                requirement_key=requirement.requirement_key,
            )
        _save_verification(state, provider_status, score, error_code, now)

    return get_status(Profile.objects.get(pk=profile.pk))
