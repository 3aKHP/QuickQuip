"""Write-only root environment administration."""
import hmac
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from quickquip.app.web import auth
from quickquip.app.web.audit import audit_logger
from quickquip.app.web.settings import get_web_admin_password
from quickquip.environment.transport import call
from quickquip.environment.store import EnvironmentError
from quickquip.app.web.routes.llm_configuration import ConfigurationRoute

router = APIRouter(prefix='/environment', route_class=ConfigurationRoute)


class Change(BaseModel):
    name: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]*$', max_length=256)
    action: Literal['create', 'replace', 'empty', 'delete']
    value: SecretStr = Field(default=SecretStr(''))


class Preview(BaseModel):
    expected_version: str
    changes: list[Change] = Field(min_length=1, max_length=256)


class Submission(Preview):
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    password: SecretStr


def invoke(action, body=None):
    try:
        return call(action, body)
    except EnvironmentError:
        raise HTTPException(409, 'Environment operation failed; refresh and retry') from None
    except OSError:
        raise HTTPException(503, 'Environment service unavailable') from None


def payload(body):
    return {'expected_version': body.expected_version, 'changes': [
        {'name': c.name, 'action': c.action, 'value': c.value.get_secret_value()}
        for c in body.changes]}


@router.get('')
def listing():
    return invoke('list')


@router.post('/preview')
def preview(body: Preview):
    return invoke('preview', payload(body))


@router.post('/changes')
def changes(body: Submission, request: Request):
    ip = auth._get_client_ip(request)
    auth._check_login_rate_limit(ip)
    if not hmac.compare_digest(body.password.get_secret_value(), get_web_admin_password()):
        auth._record_login_failure(ip)
        raise HTTPException(403, 'Administrator password incorrect')
    result = invoke('changes', {**payload(body), 'request_id': body.request_id})
    audit_logger.log(request, 'environment_change', 'environment', result['id'],
                     summary_after={'names': [c.name for c in body.changes]})
    return result


@router.get('/operations/{operation}')
def operation(operation: str):
    return invoke('operation', {'id': operation})


@router.post('/operations/{operation}/retry')
def retry(operation: str):
    return invoke('retry', {'id': operation})
