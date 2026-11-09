"""Static fixed-name catalog and packaged-template evidence for the environment directory.

Names, groups and actions here are declared facts about code and packaged
templates. Literal values, interpolation defaults and error texts from the
templates never enter any projection output.
"""
from __future__ import annotations

import re

import yaml



_P_NONEBOT = 'nonebot/config.py'
_P_ONEBOT = 'nonebot/adapters/onebot/v11/config.py'
_P_ENV_BOOT = 'nonebot/__init__.py'
_P_TRANSPORT = 'src/quickquip/environment/transport.py'
_P_ENV = 'src/quickquip/common/env.py'
_P_DOTENV = 'src/quickquip/common/dotenv.py'
_P_STORE = 'src/quickquip/environment/store.py'
_P_TIEBA = 'src/quickquip/tieba/config.py'
_P_SESSION = 'src/quickquip/app/web/session_store.py'
_P_AUTH = 'src/quickquip/app/web/auth.py'
_P_PERIOD = 'src/quickquip/chat/period_serializer.py'
_P_TRACE = 'src/quickquip/llm/provider/trace.py'
_P_MEDIA = 'src/quickquip/llm/provider/media_truncator.py'
_P_SEARCH = 'src/quickquip/search/web_search.py'
_P_DEPLOY = 'src/quickquip/configuration/deployment.py'
_P_DEPLOY_STATE = 'scripts/deploy/server/deploy-state.py'
_P_HOST_FILES = 'src/quickquip/config_sync/host_files.py'
_P_SUPERVISOR = 'src/quickquip/configuration/process_supervisor.py'

SERVICE_IDS = {'quickquip': 'bot', 'web-admin': 'web', 'env-agent': 'env-agent',
               'llbot': 'llbot', 'searxng': 'searxng', 'config-init': 'config-init'}
TEMPLATE_FILES = ('prod.example/docker-compose.yml', 'docker-compose.example.yml')
_INTERPOLATION = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::[-?][^}]*)?\}')
BUILD_TEMPLATES = {
    'docker/Dockerfile.prod': 'quickquip-app',
    'docker/mcp-fetch.Dockerfile': 'mcp-fetch',
    'docker/mcp-tavily.Dockerfile': 'mcp-tavily',
}


def make_relation(*, component, object_id, field_path, config_scope, enabled, required,
                  name_kind, source_name, raw_expression, target_service, target_kind,
                  target_name, resolution, delivery, required_action,
                  default_present=False, observation='not_observed'):
    relation = {
        'component': component,
        'object_id': object_id,
        'field_path': field_path,
        'config_scope': config_scope,
        'enabled': enabled,
        'required': required,
        'name_kind': name_kind,
        'source_name': source_name,
        'raw_expression': raw_expression,
        'target_service': target_service,
        'target_kind': target_kind,
        'target_name': target_name,
        'resolution': resolution,
        'delivery': delivery,
        'required_action': required_action,
        'observation': observation,
    }
    if default_present:
        relation['default_present'] = True
    return relation


def _code(component, *, action='restart_or_recreate', delivery='process_env',
          target_service='bot', target_kind='environment_name', path='', required=None,
          target_name=None, resolution='process'):
    return {
        'component': component, 'action': action, 'delivery': delivery,
        'target_service': target_service, 'target_kind': target_kind, 'path': path,
        'required': required, 'target_name': target_name, 'resolution': resolution,
    }


def _entry(description, value_type, groups, relations, *, suggest=False,
           internal=False, alias_of=None, default_present=False, default_origin=None):
    return {
        'description': description,
        'value_type': value_type,
        'groups': list(groups),
        'relations': relations,
        'suggest': suggest,
        'internal': internal,
        'alias_of': alias_of,
        'default_present': default_present,
        'default_origin': default_origin,
    }


def _tieba_relations():
    return [_code('tieba.service', path='src/quickquip/common/runtime_environment.py',
                  action='next_tieba_task')]


CATALOG = {
    # 运行与内置功能 — Bot 与连接
    'DRIVER': _entry('NoneBot 驱动；进程启动时读取', 'string', ['runtime.bot'],
                     [_code('framework.nonebot', path=_P_NONEBOT,
                            target_kind='config_field')], default_present=True,
                     default_origin='compose_template'),
    'HOST': _entry('Bot 服务监听地址；进程启动时读取', 'string', ['runtime.bot'],
                   [_code('framework.nonebot', path=_P_NONEBOT,
                          target_kind='config_field')]),
    'PORT': _entry('Bot 服务监听端口；进程启动时读取', 'int', ['runtime.bot'],
                   [_code('framework.nonebot', path=_P_NONEBOT,
                          target_kind='config_field')]),
    'ONEBOT_ACCESS_TOKEN': _entry('OneBot 连接访问令牌；Bot 启动与 LLBot 部署配置写入使用',
                                  'secret', ['runtime.bot'],
                                  [_code('framework.onebot', path=_P_ONEBOT,
                                         target_kind='config_field'),
                                   _code('configuration.deploy', path=_P_DEPLOY_STATE,
                                         action='redeploy', target_service='llbot',
                                         delivery='config_write')],
                                  default_present=True, default_origin='compose_template'),
    'ONEBOT_WS_URLS': _entry('OneBot 正向 WebSocket 地址列表；Bot 启动时读取', 'list',
                             ['runtime.bot'],
                             [_code('framework.onebot', path=_P_ONEBOT,
                                    target_kind='config_field')], default_present=True,
                             default_origin='compose_template'),
    'ONEBOT_SECRET': _entry('OneBot 适配器密钥；Bot 启动时读取', 'secret', ['runtime.bot'],
                            [_code('framework.onebot', path=_P_ONEBOT,
                                   target_kind='config_field')]),
    'ONEBOT_API_ROOTS': _entry('OneBot API 根地址列表；Bot 启动时读取', 'list', ['runtime.bot'],
                               [_code('framework.onebot', path=_P_ONEBOT,
                                      target_kind='config_field')]),
    'QQ_ACCOUNT': _entry('Bot QQ 账号；Bot 自身账号识别与 LLBot 登录映射使用', 'string',
                         ['runtime.bot'],
                         [_code('chat.period_serializer', path=_P_PERIOD),
                          _code('compose.llbot', path='prod.example/docker-compose.yml',
                                action='restart_or_recreate', target_service='llbot',
                                target_kind='environment_name', target_name='QUICK_LOGIN_QQ',
                                delivery='container_env', required=True)],
                         suggest=True),
    # 运行与内置功能 — 管理与会话
    'WEB_ADMIN_HOST': _entry('Web 管理后台监听地址；Web 进程启动时读取', 'string',
                             ['runtime.admin'],
                             [_code('web_api', path='web_api.py', target_service='web',
                                    target_kind='config_field')]),
    'WEB_ADMIN_PORT': _entry('Web 管理后台监听端口；Web 进程启动时读取', 'int',
                             ['runtime.admin'],
                             [_code('web_api', path='web_api.py', target_service='web',
                                    target_kind='config_field')]),
    'WEB_ADMIN_PASSWORD': _entry('Web 管理后台登录口令；进程启动时读取，修改后需重启',
                                 'secret', ['runtime.admin'],
                                 [_code('app.web.auth', path=_P_AUTH)]),
    'WEB_ADMIN_COOKIE_SECURE': _entry('Web 管理会话 Cookie Secure 标记；进程启动时读取',
                                      'bool', ['runtime.admin'],
                                      [_code('app.web', path=_P_SESSION)]),
    'WEB_ADMIN_SESSION_TTL_HOURS': _entry('Web 管理会话有效期（小时）；进程启动时读取',
                                          'int', ['runtime.admin'],
                                          [_code('app.web', path=_P_SESSION)]),
    'WEB_ADMIN_SESSION_MAX_AGE_HOURS': _entry('Web 管理会话最大存活（小时）；进程启动时读取',
                                              'int', ['runtime.admin'],
                                              [_code('app.web', path=_P_SESSION)]),
    'QUICKQUIP_ENV_MANAGEMENT_ENABLED': _entry(
        '环境管理开关；进程启动时固定，打包模板中被编排固定为 true',
        'bool', ['runtime.admin'],
        [_code('common.env', path=_P_ENV),
         _code('compose', path='prod.example/docker-compose.yml',
               action='edit_compose_then_recreate', delivery='container_env_fixed')]),
    'QUICKQUIP_ENV_SOCKET': _entry('环境只读 Socket 路径；编排注入，进程启动时固定',
                                   'string', ['runtime.admin'],
                                   [_code('environment.transport', path=_P_TRANSPORT)]),
    'QUICKQUIP_ENV_WRITE_SOCKET': _entry('环境写入 Socket 路径；编排注入，进程启动时固定',
                                         'string', ['runtime.admin'],
                                         [_code('environment.transport', path=_P_TRANSPORT)]),
    'QUICKQUIP_ENV_ROOT': _entry('环境代理的部署根路径；编排注入，进程启动时固定',
                                 'string', ['runtime.admin'],
                                 [_code('environment.transport', path=_P_TRANSPORT)]),
    # 运行与内置功能 — 贴吧
    'TIEBA_FORUM_KEYWORD': _entry('贴吧论坛关键词；任务边界热更新', 'string',
                                  ['runtime.tieba'], _tieba_relations()),
    'TIEBA_FORUM_KEYWORDS': _entry('贴吧论坛关键词列表；任务边界热更新', 'list',
                                   ['runtime.tieba'], _tieba_relations()),
    'TIEBA_ENABLED': _entry('贴吧同步总开关；进程启动时读取', 'bool', ['runtime.tieba'],
                            [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_SYNC_INTERVAL_SECONDS': _entry('贴吧同步间隔（秒）；进程启动时读取', 'int',
                                          ['runtime.tieba'],
                                          [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_MAX_POOL_SIZE': _entry('贴吧浏览器池大小；进程启动时读取', 'int', ['runtime.tieba'],
                                  [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_DETAIL_FETCH_LIMIT': _entry('贴吧详情抓取上限；进程启动时读取', 'int',
                                       ['runtime.tieba'],
                                       [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_RECENT_SENT_LIMIT': _entry('贴吧近期已发跳过上限；进程启动时读取', 'int',
                                      ['runtime.tieba'],
                                      [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_RANDOM_AVOID_RECENT': _entry('贴吧随机贴回避近期开关；进程启动时读取', 'bool',
                                        ['runtime.tieba'],
                                        [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_PREFER_IMAGE_THREADS': _entry('贴吧优先图文贴开关；进程启动时读取', 'bool',
                                         ['runtime.tieba'],
                                         [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_BROWSER_HEADLESS': _entry('贴吧浏览器无头模式；进程启动时读取', 'bool',
                                     ['runtime.tieba'],
                                     [_code('tieba.config', path=_P_TIEBA)]),
    'TIEBA_BROWSER_CHANNEL': _entry('贴吧浏览器通道；进程启动时读取', 'string',
                                    ['runtime.tieba'],
                                    [_code('tieba.config', path=_P_TIEBA)]),
    # 运行与内置功能 — Trace
    'LLM_TRACE_FLAG_FILE': _entry('Trace 启用标记文件路径；模块导入时固定', 'string',
                                  ['runtime.trace'],
                                  [_code('llm.trace', path=_P_TRACE,
                                         target_service='bot')]),
    'LLM_TRACE_MEDIA_MIN_BYTES': _entry('Trace 媒体最小记录字节数；全局构造时读取', 'int',
                                        ['runtime.trace'],
                                        [_code('llm.media_truncator',
                                               path=_P_MEDIA,
                                               target_service='bot')]),
    # 运行与内置功能 — 框架与系统
    'TZ': _entry('时区；进程启动时读取', 'string', ['runtime.framework'],
                 [_code('framework', path=_P_STORE)],
                 default_present=True, default_origin='compose_template'),
    'ENVIRONMENT': _entry('NoneBot 环境名，选择附加 .env.<environment> 文件；启动时读取',
                          'string', ['runtime.framework'],
                          [_code('framework.nonebot', path=_P_ENV_BOOT,
                                 target_kind='config_field',
                                 delivery='framework_env_file')]),
    'LOG_LEVEL': _entry('NoneBot 日志级别；进程启动时读取', 'string', ['runtime.framework'],
                        [_code('framework.nonebot', path=_P_NONEBOT,
                               target_kind='config_field')]),
    'API_TIMEOUT': _entry('NoneBot API 超时（秒）；进程启动时读取', 'int', ['runtime.framework'],
                          [_code('framework.nonebot', path=_P_NONEBOT,
                                 target_kind='config_field')]),
    'SUPERUSERS': _entry('NoneBot 超级用户列表；进程启动时读取', 'list', ['runtime.framework'],
                         [_code('framework.nonebot', path=_P_NONEBOT,
                                target_kind='config_field')]),
    'NICKNAME': _entry('Bot 昵称列表；进程启动时读取', 'list', ['runtime.framework'],
                       [_code('framework.nonebot', path=_P_NONEBOT,
                              target_kind='config_field')]),
    'COMMAND_START': _entry('命令起始前缀；进程启动时读取', 'list', ['runtime.framework'],
                            [_code('framework.nonebot', path=_P_NONEBOT,
                                   target_kind='config_field')]),
    'COMMAND_SEP': _entry('命令分隔符；进程启动时读取', 'list', ['runtime.framework'],
                          [_code('framework.nonebot', path=_P_NONEBOT,
                                 target_kind='config_field')]),
    'SESSION_EXPIRE_TIMEOUT': _entry('会话过期时间（秒）；进程启动时读取', 'int',
                                     ['runtime.framework'],
                                     [_code('framework.nonebot', path=_P_NONEBOT,
                                            target_kind='config_field')]),
    'PYTHON_DOTENV_DISABLED': _entry(
        '在读取根 .env 之前由进程环境判定；写入根 .env 不能阻止本次加载',
        'bool', ['runtime.framework'],
        [_code('common.dotenv', path=_P_DOTENV)]),
    'QUICKQUIP_MANAGED_CONTAINER': _entry('容器化标记；编排注入，进程启动时固定', 'bool',
                                          ['runtime.framework'],
                                          [_code('environment.transport',
                                                 path=_P_TRANSPORT)]),
    # 服务与扩展 — 搜索
    'SEARXNG_BASE_URL': _entry('SearXNG 实例地址；Bot/Web 进程内读取，容器部署时由编排映射注入',
                               'string', ['services.native.search'],
                               [_code('search.web_search', path=_P_SEARCH)]),
    'SEARXNG_SAFE_SEARCH': _entry('SearXNG 安全搜索级别；请求时读取', 'string',
                                  ['services.native.search'],
                                  [_code('search.web_search', path=_P_SEARCH)],
                                  default_present=True, default_origin='code'),
    'SEARXNG_LANGUAGE': _entry('SearXNG 搜索语言；请求时读取', 'string',
                               ['services.native.search'],
                               [_code('search.web_search', path=_P_SEARCH)],
                               default_present=True, default_origin='code'),
    'QUICKQUIP_SEARXNG_BASE_URL': _entry(
        '外部 SearXNG 地址；由编排映射为容器内 SEARXNG_BASE_URL，根值经 Compose 插值生效',
        'string', ['services.native.search'],
        [_code('compose', path='prod.example/docker-compose.yml',
               action='restart_or_recreate', delivery='container_env',
               target_kind='environment_name', target_name='SEARXNG_BASE_URL',
               required=True)],
        suggest=True),
    'SEARXNG_SECRET': _entry('自包含模板 SearXNG 实例密钥；仅 docker-compose.example.yml 使用',
                             'secret', ['runtime.framework'],
                             [_code('compose.searxng', path='docker-compose.example.yml',
                                    action='restart_or_recreate', target_service='searxng',
                                    delivery='container_env')]),
    'SEARXNG_PUBLIC_BASE_URL': _entry(
        '自包含模板对外 SearXNG 基址；映射为 searxng 容器 SEARXNG_BASE_URL',
        'string', ['runtime.framework'],
        [_code('compose.searxng', path='docker-compose.example.yml',
               action='restart_or_recreate', target_service='searxng',
               delivery='container_env', target_kind='environment_name',
               target_name='SEARXNG_BASE_URL')],
        default_present=True, default_origin='compose_template'),
    'SEARXNG_BIND_ADDRESS': _entry('自包含模板 SearXNG 端口发布地址；同时是容器内固定值',
                                   'string', ['runtime.framework'],
                                   [_code('compose.searxng', path='docker-compose.example.yml',
                                          action='restart_or_recreate', target_service='searxng',
                                          delivery='container_env')], default_present=True,
                                   default_origin='compose_template'),
    'SEARXNG_BIND_PORT': _entry('自包含模板 SearXNG 端口发布端口', 'int', ['runtime.framework'],
                                [_code('compose.searxng', path='docker-compose.example.yml',
                                       action='restart_or_recreate', target_service='searxng',
                                       delivery='container_env')], default_present=True,
                                default_origin='compose_template'),
    # 部署与构建 — 部署连接
    'QUICKQUIP_DEPLOY_LOCATION': _entry('部署位置模式（local/cloud）；由部署与配置工具调用时读取',
                                        'string', ['deployment.connection'],
                                        [_code('configuration.deployment',
                                               path=_P_DEPLOY,
                                               action='next_deployment', delivery='tool_read')],
                                        suggest=True),
    'QUICKQUIP_DEPLOY_RUNTIME': _entry('部署运行时（source/docker）；由部署与配置工具调用时读取',
                                        'string', ['deployment.connection'],
                                        [_code('configuration.deployment',
                                               path=_P_DEPLOY,
                                               action='next_deployment', delivery='tool_read')],
                                        suggest=True),
    'QUICKQUIP_DEPLOY_SSH_HOST': _entry('云端部署 SSH 主机；由部署与配置工具调用时读取',
                                         'string', ['deployment.connection'],
                                         [_code('configuration.deployment',
                                                path=_P_DEPLOY,
                                                action='next_deployment', delivery='tool_read')],
                                         suggest=True, default_present=True,
                                         default_origin='code'),
    'QUICKQUIP_DEPLOY_REMOTE_DIR': _entry('云端部署远端目录；由部署与配置工具调用时读取',
                                           'string', ['deployment.connection'],
                                           [_code('configuration.deployment',
                                                  path=_P_DEPLOY,
                                                  action='next_deployment', delivery='tool_read')],
                                           suggest=True, default_present=True,
                                           default_origin='code'),
    'QUICKQUIP_ROOT': _entry('部署根路径；仅供编排插值使用，不从根 .env 管理', 'string',
                             ['deployment.connection'],
                             [_code('compose', path='prod.example/docker-compose.yml',
                                    action='redeploy', delivery='container_env')],
                             internal=True, default_present=True,
                             default_origin='compose_template'),
    'QUICKQUIP_ENV_FILE': _entry('Compose env_file 路径；仅供编排插值使用', 'string',
                                 ['deployment.connection'],
                                 [_code('compose', path='prod.example/docker-compose.yml',
                                        action='redeploy', delivery='container_env')],
                                 internal=True, default_present=True,
                                 default_origin='compose_template'),
    'QUICKQUIP_RELEASE': _entry('镜像标签；仅供编排插值使用', 'string',
                                ['deployment.connection'],
                                [_code('compose', path='prod.example/docker-compose.yml',
                                       action='redeploy', delivery='container_env')],
                                internal=True, default_present=True,
                                default_origin='compose_template'),
    # 部署与构建 — 镜像与依赖
    'PIP_INDEX_URL': _entry('镜像构建 pip 源；构建参数传入，需重新构建镜像',
                            'string', ['deployment.image'],
                            [_code('image.build', path='docker/Dockerfile.prod',
                                   action='rebuild_image', delivery='build_arg')],
                            suggest=True, default_present=True,
                            default_origin='compose_template'),
    'PIP_TRUSTED_HOST': _entry('镜像构建 pip 可信主机；构建参数传入，需重新构建镜像',
                               'string', ['deployment.image'],
                               [_code('image.build', path='docker/Dockerfile.prod',
                                      action='rebuild_image', delivery='build_arg')],
                               suggest=True, default_present=True,
                               default_origin='compose_template'),
    'PLAYWRIGHT_BASE_IMAGE': _entry('Playwright 基础镜像；首个 FROM 前的构建参数',
                                    'string', ['deployment.image'],
                                    [_code('image.build', path='docker/Dockerfile.prod',
                                           action='rebuild_image', delivery='build_arg')],
                                    suggest=True, default_present=True,
                                    default_origin='compose_template'),
    # 内部项（编排/进程内部，不提供根 .env 新增建议）
    'QUICK_LOGIN_QQ': _entry('LLBot 登录账号；由 QQ_ACCOUNT 经编排映射注入', 'string',
                             ['runtime.bot'],
                             [_code('compose.llbot', path='prod.example/docker-compose.yml',
                                    action='restart_or_recreate', target_service='llbot',
                                    delivery='container_env')],
                             internal=True),
    'PYTHONPATH': _entry('容器内 Python 路径；编排固定', 'string', ['runtime.framework'],
                         [_code('compose', path='prod.example/docker-compose.yml',
                                action='edit_compose_then_recreate',
                                delivery='container_env_fixed')], internal=True),
    'PYTHONUNBUFFERED': _entry('镜像内 Python 输出不缓冲；镜像固定', 'bool',
                               ['runtime.framework'],
                               [_code('image.env', path='docker/Dockerfile.prod',
                                      action='rebuild_image', delivery='container_env_fixed')],
                               internal=True),
    'SEARXNG_PORT': _entry('searxng 容器内端口；编排固定', 'int', ['runtime.framework'],
                           [_code('compose.searxng', path='docker-compose.example.yml',
                                  action='edit_compose_then_recreate',
                                  target_service='searxng',
                                  delivery='container_env_fixed')], internal=True),
    'SEARXNG_LIMITER': _entry('searxng 限流开关；编排固定', 'bool', ['runtime.framework'],
                              [_code('compose.searxng', path='docker-compose.example.yml',
                                     action='edit_compose_then_recreate',
                                     target_service='searxng',
                                     delivery='container_env_fixed')], internal=True),
    'FORCE_OWNERSHIP': _entry('searxng 目录属主接管；编排固定', 'bool', ['runtime.framework'],
                              [_code('compose.searxng', path='docker-compose.example.yml',
                                     action='edit_compose_then_recreate',
                                     target_service='searxng',
                                     delivery='container_env_fixed')], internal=True),
    'QUICKQUIP_SYNC_UID': _entry('配置同步 helper 的宿主 UID；工具注入', 'int',
                                 ['deployment.connection'],
                                 [_code('config_sync.host_files',
                                        path=_P_HOST_FILES,
                                        action='next_deployment', delivery='tool_read')],
                                 internal=True),
    'QUICKQUIP_SYNC_GID': _entry('配置同步 helper 的宿主 GID；工具注入', 'int',
                                 ['deployment.connection'],
                                 [_code('config_sync.host_files',
                                        path=_P_HOST_FILES,
                                        action='next_deployment', delivery='tool_read')],
                                 internal=True),
    '_QUICKQUIP_SERVICE_CHILD': _entry('进程监督器子进程标记；运行时注入', 'bool',
                                       ['runtime.framework'],
                                       [_code('configuration.process_supervisor',
                                              path=_P_SUPERVISOR)],
                                       internal=True),
    '_QUICKQUIP_SERVICE_CHILD_ID': _entry('进程监督器子进程标识；运行时注入', 'string',
                                          ['runtime.framework'],
                                          [_code('configuration.process_supervisor',
                                                 path=_P_SUPERVISOR)],
                                          internal=True),
    '_QUICKQUIP_SERVICE_SUPERVISOR_ID': _entry('进程监督器标识；运行时注入', 'string',
                                               ['runtime.framework'],
                                               [_code('configuration.process_supervisor',
                                                      path=_P_SUPERVISOR)],
                                               internal=True),
}
for _alias, _canonical in (
    ('ONEBOT_V11_ACCESS_TOKEN', 'ONEBOT_ACCESS_TOKEN'),
    ('ONEBOT_V11_SECRET', 'ONEBOT_SECRET'),
    ('ONEBOT_V11_WS_URLS', 'ONEBOT_WS_URLS'),
    ('ONEBOT_V11_API_ROOTS', 'ONEBOT_API_ROOTS'),
):
    CATALOG[_alias] = _entry(
        f'OneBot V11 别名，等效于 {_canonical}', 'string', ['runtime.bot'],
        [_code('framework.onebot', path=_P_ONEBOT,
               target_kind='config_field')],
        alias_of=_canonical)


def _template_sources(root):
    """Parse packaged compose templates into name-only evidence, never values."""
    usages = []
    errors = []
    for relative in TEMPLATE_FILES:
        path = root / relative
        if not path.exists():
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            errors.append({'component': 'compose_template', 'code': 'directory_source_unavailable'})
            continue
        services = document.get('services', {}) if isinstance(document, dict) else {}
        if not isinstance(services, dict):
            continue
        template = relative
        for service, definition in services.items():
            if not isinstance(definition, dict):
                continue
            target_service = SERVICE_IDS.get(service, service)
            usages.extend(_service_usages(
                definition, target_service, template, f'services.{service}'))
    return usages, errors


def _service_usages(definition, target_service, template, base):
    usages = []
    environment = definition.get('environment', [])
    entries = environment.items() if isinstance(environment, dict) else (
        (item.split('=', 1)[0], item.split('=', 1)[1] if '=' in item else None)
        for item in environment if isinstance(item, str))
    for target, value in entries:
        usages.extend(_env_entry_usages(
            str(target), value, target_service, template, f'{base}.environment.{target}'))
    build = definition.get('build', {})
    args = build.get('args', {}) if isinstance(build, dict) else {}
    if isinstance(args, dict):
        for arg, value in args.items():
            usages.extend(_arg_usages(
                str(arg), value, template, f'{base}.build.args.{arg}'))
    for field in ('image',):
        usages.extend(_scan_interpolations(
            definition.get(field), 'deployment.connection', 'container_env', 'redeploy',
            template, f'{base}.{field}'))
    env_file = definition.get('env_file')
    files = env_file if isinstance(env_file, list) else [env_file]
    for item in files:
        usages.extend(_scan_interpolations(
            item, 'deployment.connection', 'container_env', 'redeploy',
            template, f'{base}.env_file'))
    for volume in definition.get('volumes', []) or []:
        if isinstance(volume, str):
            usages.extend(_scan_interpolations(
                volume, 'deployment.connection', 'container_env', 'redeploy',
                template, f'{base}.volumes'))
    for port in definition.get('ports', []) or []:
        if isinstance(port, str):
            usages.extend(_scan_interpolations(
                port, 'runtime.framework', 'container_env', 'restart_or_recreate',
                template, f'{base}.ports'))
    return usages


def _env_entry_usages(target, value, target_service, template, path):
    if value is None:
        return [{
            'name': target, 'group': 'runtime.framework', 'internal_only': True,
            'relation': make_relation(
                component='compose', object_id=None, field_path=path,
                config_scope='template', enabled=None, required=None, name_kind='fixed',
                source_name=target, raw_expression=target,
                target_service=target_service, target_kind='environment_name',
                target_name=target, resolution='compose', delivery='container_env',
                required_action='restart_or_recreate'),
            'source': _source(template, path, 'compose', 'container_env'),
        }]
    text = str(value)
    matches = _INTERPOLATION.findall(text)
    if not matches:
        if '$$' in text:
            return []
        return [{
            'name': target, 'group': 'runtime.framework', 'internal_only': True,
            'relation': make_relation(
                component='compose', object_id=None, field_path=path,
                config_scope='template', enabled=None, required=None, name_kind='fixed',
                source_name=target, raw_expression=target,
                target_service=target_service, target_kind='environment_name',
                target_name=target, resolution='compose',
                delivery='container_env_fixed',
                required_action='edit_compose_then_recreate'),
            'source': _source(template, path, 'compose', 'container_env_fixed',
                              override_kind='compose_static'),
        }]
    usages = []
    for name in dict.fromkeys(matches):
        has_default = re.search(r'\$\{' + re.escape(name) + r':-', text) is not None
        required = re.search(r'\$\{' + re.escape(name) + r':\?', text) is not None
        usages.append({
            'name': name, 'group': 'runtime.framework', 'internal_only': False,
            'required_from_template': required,
            'default_present': has_default,
            'relation': make_relation(
                component='compose', object_id=None, field_path=path,
                config_scope='template', enabled=None, required=None,
                name_kind='interpolation', source_name=name,
                raw_expression=f'${{{name}}}',
                target_service=target_service, target_kind='environment_name',
                target_name=target, resolution='compose', delivery='container_env',
                required_action='restart_or_recreate', default_present=has_default),
            'source': _source(template, path, 'compose_interpolation', 'container_env',
                              override_kind='compose_mapped', target_name=target),
        })
    return usages


def _arg_usages(arg, value, template, path):
    text = str(value)
    matches = _INTERPOLATION.findall(text)
    if not matches:
        return [{
            'name': arg, 'group': 'deployment.image', 'internal_only': True,
            'relation': make_relation(
                component='compose.build', object_id=None, field_path=path,
                config_scope='template', enabled=None, required=None, name_kind='fixed',
                source_name=arg, raw_expression=arg,
                target_service='image', target_kind='build_arg', target_name=arg,
                resolution='compose', delivery='build_arg',
                required_action='rebuild_image'),
            'source': _source(template, path, 'compose', 'build_arg'),
        }]
    return [{
        'name': name, 'group': 'deployment.image', 'internal_only': False,
        'relation': make_relation(
            component='compose.build', object_id=None, field_path=path,
            config_scope='template', enabled=None, required=None,
            name_kind='interpolation', source_name=name, raw_expression=f'${{{name}}}',
            target_service='image', target_kind='build_arg', target_name=arg,
            resolution='compose', delivery='build_arg', required_action='rebuild_image'),
        'source': _source(template, path, 'compose_interpolation', 'build_arg',
                          override_kind='compose_mapped', target_name=arg),
    } for name in dict.fromkeys(matches)]


def _scan_interpolations(value, group, delivery, action, template, path):
    if not isinstance(value, str):
        return []
    return [{
        'name': name, 'group': group, 'internal_only': False,
        'relation': make_relation(
            component='compose', object_id=None, field_path=path,
            config_scope='template', enabled=None, required=None,
            name_kind='interpolation', source_name=name, raw_expression=f'${{{name}}}',
            target_service='compose', target_kind='config_field', target_name=path,
            resolution='compose', delivery=delivery, required_action=action),
        'source': _source(template, path, 'compose_interpolation', delivery),
    } for name in dict.fromkeys(_INTERPOLATION.findall(value))]


def _source(template, path, kind, delivery, *, override_kind=None, target_name=None):
    source = {
        'kind': kind,
        'context': template,
        'path': path,
        'raw_expression': None,
        'resolution_context': 'compose_interpolation' if kind == 'compose_interpolation'
        else 'compose',
        'evidence_scope': 'compose_template',
        'observation': 'not_observed',
    }
    if override_kind:
        source['override_kind'] = override_kind
    if target_name:
        source['target_name'] = target_name
    return source


def _dockerfile_sources(root):
    """Attach packaged Dockerfile ARG declarations as build evidence."""
    usages = []
    errors = []
    for relative, image in BUILD_TEMPLATES.items():
        path = root / relative
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeDecodeError):
            errors.append({'component': 'dockerfile', 'code': 'directory_source_unavailable'})
            continue
        for line in lines:
            match = re.match(r'\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)', line)
            if not match:
                continue
            name = match.group(1)
            usages.append({
                'name': name, 'group': 'deployment.image', 'internal_only': True,
                'relation': make_relation(
                    component='image.build', object_id=image,
                    field_path=f'{relative}:ARG {name}',
                    config_scope='template', enabled=None, required=None,
                    name_kind='fixed', source_name=name, raw_expression=name,
                    target_service='image', target_kind='build_arg', target_name=name,
                    resolution='image_build', delivery='build_arg',
                    required_action='rebuild_image'),
                'source': {
                    'kind': 'dockerfile', 'context': relative,
                    'path': f'{relative}:ARG {name}', 'raw_expression': None,
                    'resolution_context': 'image_build', 'evidence_scope': 'code',
                    'observation': 'not_observed',
                },
            })
    return usages, errors


def fixed_usages(root):
    """Return (usages, errors) for catalog code consumers and packaged templates."""
    usages = []
    for name, entry in CATALOG.items():
        for relation in entry['relations']:
            target_name = relation.get('target_name', name)
            usages.append({
                'name': name,
                'group': entry['groups'],
                'internal_only': entry['internal'],
                'fixed_entry': entry,
                'relation': make_relation(
                    component=relation['component'], object_id=None,
                    field_path=relation['path'], config_scope='code',
                    enabled=None, required=relation.get('required'), name_kind='fixed',
                    source_name=name, raw_expression=name,
                    target_service=relation.get('target_service', 'bot'),
                    target_kind=relation.get('target_kind', 'environment_name'),
                    target_name=target_name, resolution=relation.get('resolution', 'process'),
                    delivery=relation['delivery'],
                    required_action=relation['action']),
                'source': {
                    'kind': 'code', 'context': 'code', 'path': relation['path'],
                    'raw_expression': None,
                    'resolution_context': relation.get('resolution', 'process'),
                    'evidence_scope': 'code', 'observation': 'not_observed',
                },
            })
    template_usages, template_errors = _template_sources(root)
    build_usages, build_errors = _dockerfile_sources(root)
    return usages + template_usages + build_usages, template_errors + build_errors
