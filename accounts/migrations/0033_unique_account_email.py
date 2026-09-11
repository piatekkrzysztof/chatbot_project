from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower, Trim


def check_collisions(apps, schema_editor):
    users = apps.get_model("accounts", "CustomUser").objects.using(schema_editor.connection.alias)
    collisions = (users.exclude(email="").annotate(canonical=Lower(Trim("email")))
                  .values("canonical").annotate(total=Count("pk")).filter(total__gt=1).count())
    if collisions:
        raise RuntimeError(
            f"Cannot enforce unique email: {collisions} conflicting groups. "
            "Resolve account ownership before retrying; no accounts were changed."
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0032_message_reservations")]
    operations = [
        migrations.RunPython(check_collisions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="customuser",
            constraint=models.UniqueConstraint(
                Lower(Trim("email")), condition=~models.Q(email=""), name="account_email_ci_unique"
            ),
        ),
    ]
