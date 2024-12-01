from django.apps import AppConfig
import pluggy

pm = None


def get_plugin_manager():
    return pm


class MissionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "missions"

    def ready(self):
        global pm
        from missions import hookspecs
        from .plugins import (
            linear,
            github,
            figma,
            jira,
            notion,
            monday,
            sentry,
            slack,
            harvest,
            openai,
            anthropic,
            gemini,
            mistral,
            quantify,
            agent,
            fetch,
            evals,
            scrape,
            bing,
            nemotron,
            # Import other files with plugins here
        )

        pm = pluggy.PluginManager("YamLLMs")
        pm.add_hookspecs(hookspecs)
        pm.register(github)
        pm.register(jira)
        pm.register(linear)
        pm.register(notion)
        pm.register(figma)
        pm.register(monday)
        pm.register(sentry)
        pm.register(slack)
        pm.register(harvest)
        pm.register(openai)
        pm.register(gemini)
        pm.register(anthropic)
        pm.register(mistral)
        pm.register(quantify)
        pm.register(agent)
        pm.register(fetch)
        pm.register(evals)
        pm.register(scrape)
        pm.register(bing)
        pm.register(nemotron)
        # Add other plugins here
