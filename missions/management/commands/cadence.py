import datetime
from django.core.management.base import BaseCommand
from missions.models import MissionInfo, Customer
from missions.hub import fulfil_mission
from missions.util import is_sqlite, log


class Command(BaseCommand):
    help = "Run cadence reports"

    def add_arguments(self, parser):
        parser.add_argument("--customer_id", help="Customer ID")
        parser.add_argument("--dry_run", help="Dry run")
        parser.add_argument("--data_missions_only", help="Only run data missions")

    def handle(self, *args, **options):
        customer = None
        if options["customer_id"]:
            customer = Customer.objects.filter(id=options["customer_id"]).first()

        mission_infos = MissionInfo.objects.filter(cadence=MissionInfo.Cadence.DAILY)
        if customer:
            mission_infos = mission_infos.filter(customer_id=options["customer_id"])
        if options["dry_run"]:
            log("Dry run: customer", customer)
        if mission_infos:
            if options["dry_run"]:
                log("Dry run: daily reports", customer)
            else:
                log("Running daily reports: count", mission_infos.count(), customer)
                for mi in mission_infos:
                    self.run_report(mi)

        weekday = datetime.datetime.now().weekday()

        mission_infos = MissionInfo.objects.filter(
            cadence=MissionInfo.Cadence.WEEKLY,
            run_at=weekday,
            customer__status=Customer.CustomerStatus.ACTIVE,
        )

        if customer:
            mission_infos = mission_infos.filter(customer=customer)
        if not is_sqlite():
            mission_infos = mission_infos.exclude(
                extras__contains={"report_on_reports": "true"}
            )

        # run data missions separately
        data_mission_infos = []
        for mi in mission_infos:
            dependencies = MissionInfo.objects.filter(depends_on=mi)
            if dependencies:
                log("Adding data mission", mi, "dependencies", dependencies)
                data_mission_infos.append(mi)
        if options["data_missions_only"]:
            log("Running weekly data missions only")
            mission_infos = data_mission_infos
        else:
            mission_infos = mission_infos.exclude(
                id__in=[mi.id for mi in data_mission_infos]
            )

        if mission_infos:
            if options["dry_run"]:
                log("Dry run: weekly reports", mission_infos)
            else:
                log("Running weekly reports", mission_infos)
                for mi in mission_infos:
                    self.run_report(mi)

    def run_report(self, mi):
        if mi.depends_on and not mi.depends_on.latest_mission():
            log("Skipping report:", mi.name, "due to missing dependency")
        else:
            log("Running report:", mi.name)
            mission = mi.create_mission()
            fulfil_mission.delay(mission.id)
