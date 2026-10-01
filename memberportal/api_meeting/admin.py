from django.contrib import admin
from .models import Meeting, ProxyVote


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    pass


@admin.register(ProxyVote)
class ProxyVoteAdmin(admin.ModelAdmin):
    pass
