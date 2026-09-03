from django.conf import settings
from constance import config
import json
import logging
import requests
import sentry_sdk

logger = logging.getLogger("docuseal")


def create_submission_for_subscription(profile):
    try:
        full_name = "{} {}".format(profile.first_name, profile.last_name)

        # Pre-fill the member (first party) with the profile values we already
        # have, keyed by field name via "values". Unlike "fields", DocuSeal
        # ignores "values" keys that don't exist on the template, so this
        # won't 422 if the template lacks one of these fields. Add matching
        # fields in the DocuSeal template.
        submitters = [
            {
                "role": "First Party",
                "name": full_name,
                "email": profile.user.email,
                "values": {
                    "First Name": profile.first_name,
                    "Last Name": profile.last_name,
                    "Full Name": full_name,
                    "Email": profile.user.email,
                    "Phone": profile.phone,
                },
            }
        ]

        # Append any statically-configured additional signers (e.g. witness or org).
        try:
            additional_signers = json.loads(config.DOCUSEAL_ADDITIONAL_SIGNERS or "[]")
            if isinstance(additional_signers, list):
                submitters.extend(additional_signers)
            else:
                logger.error(
                    "DOCUSEAL_ADDITIONAL_SIGNERS must be a JSON array, got %s; "
                    "ignoring.",
                    type(additional_signers).__name__,
                )
        except (ValueError, TypeError) as ex:
            logger.error(
                "DOCUSEAL_ADDITIONAL_SIGNERS is not valid JSON ({}); "
                "ignoring.".format(ex)
            )

        data = {
            # template_id must be a JSON integer; Constance may hand back a string
            "template_id": int(config.DOCUSEAL_TEMPLATE_ID),
            ### Customize the following to fit your instance deployment and template
            "send_email": False,
            "completed_redirect_url": config.SITE_URL,
            "submitters": submitters,
        }

        body = json.dumps(data)
        logger.info("Submitting to Docuseal with body:\n{}".format(body))

        response = requests.post(
            url=config.DOCUSEAL_URL + "/api/submissions",
            headers={
                "X-Auth-Token": config.DOCUSEAL_API_KEY,
                "Content-Type": "application/json",
            },
            data=body,
        )

        # Surface DocuSeal's rejection body
        if not response.ok:
            ex = ValueError(
                "DocuSeal returned {}: {}".format(response.status_code, response.text)
            )
            with sentry_sdk.push_scope() as scope:
                scope.set_context(
                    "docuseal_submission",
                    {
                        "status_code": response.status_code,
                        "response_body": response.text,
                        "template_id": data["template_id"],
                        "request_body": body,
                    },
                )
                sentry_sdk.capture_exception(ex)
            raise ex
        res = response.json()[0]
        logger.debug("Got response:\n{}".format(res))
    except Exception as ex:
        # holy overly-broad exception handlers batman!
        logger.error("Submission creation failed!\n{}".format(ex))
        raise ex

    logger.debug(
        "Created submission {} with slug {}".format(res["submission_id"], res["slug"])
    )
    profile.memberdoc_id = res["submission_id"]
    profile.memberdoc_url = res["embed_src"]
    profile.save()


def get_docuseal_submission(profile):
    if profile.memberdoc_id is None:
        return None

    logger.debug(
        "Requesting {}".format("/api/submissions/" + str(profile.memberdoc_id))
    )
    try:
        response = requests.get(
            url=config.DOCUSEAL_URL + "/api/submissions/" + str(profile.memberdoc_id),
            headers={"X-Auth-Token": config.DOCUSEAL_API_KEY},
        )
        logger.debug("Got response:\n{}".format(response.json()))
        state = response.json()
    except Exception as ex:
        # holy overly-broad exception handlers batman!
        logger.error("Finding submission state failed!\n{}".format(ex))
        raise ex

    return state


# DocuSeal reports a fully-signed submission as status "completed", but the
# key ("status" vs "state") and value ("complete" vs "completed") have varied
# across versions / the self-hosted build. Read it tolerantly rather than
# hard-coding one spelling.
_DOCUSEAL_COMPLETE_VALUES = {"complete", "completed"}
_DOCUSEAL_DECLINED_VALUES = {"decline", "declined"}


def _submission_status(submission):
    """Return the submission's status string, tolerating status/state keys."""
    if not isinstance(submission, dict):
        return None
    return submission.get("status") or submission.get("state")


def submission_is_complete(submission):
    """True when every party has signed the submission.

    Accepts the status-string variants above, and falls back to the
    submission-level ``completed_at`` timestamp when present.
    """
    status = _submission_status(submission)
    if status and status.lower() in _DOCUSEAL_COMPLETE_VALUES:
        return True
    if isinstance(submission, dict) and submission.get("completed_at"):
        return True
    return False


def submission_is_declined(submission):
    status = _submission_status(submission)
    return bool(status and status.lower() in _DOCUSEAL_DECLINED_VALUES)
