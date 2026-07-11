from __future__ import annotations

import factory

from app.schemas.tasks import TaskCreate


class TaskCreateFactory(factory.Factory):
    """Generate valid API payloads without coupling tests to database state."""

    class Meta:
        model = TaskCreate

    title = factory.Faker("sentence", nb_words=4)
    description = factory.Faker("paragraph", nb_sentences=2)
    priority = factory.Iterator([1, 2, 3, 4, 5])
    status = "todo"
    assignee = factory.Faker("email")
    tags = factory.LazyFunction(lambda: ["generated", "fixture"])
