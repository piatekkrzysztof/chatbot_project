from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from accounts.models import InvitationToken


def send_invitation_email(invitation: InvitationToken):
    """
    Wysyła e-mail z zaproszeniem do użytkownika na podstawie tokenu.
    """
    accept_url = f"{settings.FRONTEND_URL}/invite/accept/{invitation.token}"

    subject = "Zaproszenie do platformy Chatbot SaaS"
    message = f"""
Cześć!

Zostałeś zaproszony do współpracy w zespole: {invitation.tenant.name}
Rola: {invitation.role.capitalize()}

Kliknij w link, aby dołączyć:
{accept_url}

Uwaga: link wygaśnie {invitation.expires_at.strftime('%Y-%m-%d %H:%M')} i może być użyty maksymalnie {invitation.max_users} raz(y).

Pozdrawiamy,
Zespół Chatbot Platform
"""

    send_mail(
        subject=subject.strip(),
        message=message.strip(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invitation.email],
        fail_silently=False,
    )
