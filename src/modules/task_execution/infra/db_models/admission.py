from sqlalchemy import DDL, Boolean, CheckConstraint, Column, Integer, Uuid, event, false
from sqlmodel import Field, SQLModel


class TaskAdmissionControlRecord(SQLModel, table=True):
    __tablename__ = "task_admission_control"
    __table_args__ = (
        CheckConstraint("singleton = 1", name="ck_task_admission_singleton"),
        CheckConstraint("NOT frozen OR operation_id IS NOT NULL", name="ck_task_admission_frozen"),
    )

    singleton: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    operation_id: str | None = Field(default=None, sa_column=Column(Uuid(as_uuid=False)))
    frozen: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=false())
    )


event.listen(
    TaskAdmissionControlRecord.__table__,
    "after_create",
    DDL("INSERT INTO task_admission_control (singleton) VALUES (1)").execute_if(
        dialect="postgresql"
    ),
)
