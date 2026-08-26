from veritas_runtime.app_factory import create_app
from veritas_runtime.auth.routes import create_google_auth_router
from veritas_runtime.changes.routes_bootstrap import create_evidence_bootstrap_router
from veritas_runtime.command_center.routes import create_command_center_router
from veritas_runtime.composition import (
    approval_actor_resolver,
    build_api_components,
    operation_actor_resolver,
    session_principal_resolver,
    subject_resolver,
)
from veritas_runtime.email_tasks.routes import create_email_task_router
from veritas_runtime.execution.routes import create_execution_router
from veritas_runtime.lineage.routes import create_impact_router
from veritas_runtime.operations.routes import create_operations_router
from veritas_runtime.packets.routes import create_packet_router
from veritas_runtime.repairs.routes import create_repair_router
from veritas_runtime.settings import get_settings
from veritas_runtime.verification.routes import create_verification_router

settings = get_settings()
components = build_api_components(settings)
secure_cookie = settings.environment in {"preview", "production"}
app = create_app("control-api", settings)
app.state.configuration_ready = components is not None
app.include_router(
    create_google_auth_router(
        components.auth.service if components is not None else None,
        secure_cookie=secure_cookie,
        session_codec=components.session_codec if components is not None else None,
    )
)
if components is None:
    app.include_router(create_evidence_bootstrap_router(None, None))
    app.include_router(create_packet_router(None))
    app.include_router(create_impact_router(None, None))
    app.include_router(create_repair_router(None, None, None))
    app.include_router(create_execution_router(None, None))
    app.include_router(create_verification_router(None, None))
    app.include_router(create_operations_router(None, None, None))
    app.include_router(create_command_center_router(None, None))
    app.include_router(create_email_task_router(None, None))
else:
    resolve_subject = subject_resolver(components.session_codec, secure_cookie=secure_cookie)
    app.include_router(create_evidence_bootstrap_router(components.evidence, resolve_subject))
    app.include_router(create_packet_router(None, components.packets, resolve_subject))
    app.include_router(create_impact_router(components.impact, resolve_subject))
    app.include_router(
        create_repair_router(
            components.repairs,
            resolve_subject,
            approval_actor_resolver(components.session_codec, secure_cookie=secure_cookie),
        )
    )
    app.include_router(
        create_command_center_router(
            components.command_center,
            resolve_subject,
            components.approval_continuation,
            approval_actor_resolver(components.session_codec, secure_cookie=secure_cookie),
        )
    )
    app.include_router(create_execution_router(components.execution, resolve_subject))
    app.include_router(create_verification_router(components.verification, resolve_subject))
    app.include_router(
        create_operations_router(
            components.operations,
            resolve_subject,
            operation_actor_resolver(components.session_codec, secure_cookie=secure_cookie),
        )
    )
    app.include_router(
        create_email_task_router(
            components.email_tasks,
            session_principal_resolver(
                components.session_codec,
                secure_cookie=secure_cookie,
            ),
        )
    )
    app.router.add_event_handler("shutdown", components.close)


@app.get("/api/v1", tags=["system"])
async def service_root() -> dict[str, str]:
    return {"service": "control-api", "status": "available"}
