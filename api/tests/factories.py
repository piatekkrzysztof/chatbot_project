import factory
import uuid
from datetime import date, timedelta
from accounts.models import Tenant, Subscription, CustomUser
from chat.models import Conversation, ChatMessage


class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Faker("company")
    api_key = factory.LazyFunction(lambda: str(uuid.uuid4()))



class SubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subscription

    tenant = factory.SubFactory(TenantFactory)
    plan_type = "Pro"
    is_active = True
    start_date = factory.LazyFunction(lambda: date.today() - timedelta(days=1))
    end_date = factory.LazyFunction(lambda: date.today() + timedelta(days=30))


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomUser

    username = factory.Faker("user_name")
    email = factory.Faker("email")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")
    tenant = factory.SubFactory(TenantFactory)
    role = "owner"


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation

    tenant = factory.SubFactory(TenantFactory)
    user_identifier = factory.Faker("uuid4")
    source = "widget"


class ChatMessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChatMessage

    conversation = factory.SubFactory(ConversationFactory)
    sender = "user"
    message = factory.Faker("sentence")
