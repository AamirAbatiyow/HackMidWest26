"""Agent session storage: local files for dev, Akamai Object Storage (S3-compatible) when deployed."""

from __future__ import annotations

from typing import Any

from hm_agents_common.settings import AgentSettings, get_agent_settings


def make_session_manager(session_id: str, settings: AgentSettings | None = None) -> Any:
    s = settings or get_agent_settings()
    if s.session_backend == "s3":
        import boto3
        from strands.session.s3_session_manager import S3SessionManager

        from hm_storage.settings import get_storage_settings

        st = get_storage_settings()
        boto_session = boto3.Session(
            aws_access_key_id=st.object_storage_access_key.get_secret_value() or None,
            aws_secret_access_key=st.object_storage_secret_key.get_secret_value() or None,
            region_name=st.object_storage_region,
        )
        return S3SessionManager(
            session_id=session_id,
            bucket=s.session_bucket or st.object_storage_bucket,
            prefix="sessions/",
            boto_session=boto_session,
            endpoint_url=st.object_storage_endpoint or None,
        )

    from strands.session.file_session_manager import FileSessionManager

    return FileSessionManager(session_id=session_id, storage_dir=s.session_dir)
