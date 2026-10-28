"""Submit one Seedance Mini clip, then resume only the original Qiling task."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
KEY_SERVICE = "brain-comic-plus:qiling-video"
MARKER = re.compile(r"\{\{ref:([A-Z][0-9]+)\}\}")


class MissingApiKey(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(path):
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def https_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        raise ValueError("仅接受无内嵌账号密码的HTTPS地址")
    return parts


def settings():
    config = read(ROOT / "references/qiling-video.json")
    url = os.getenv("QILING_VIDEO_API_URL") or config["api_url"]
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    parts = https_url(url)
    if parts.path or parts.query or parts.fragment:
        raise ValueError("视频API地址须为平台根地址")
    return dict(api_url=url, model=config["model"])


def secure_store():
    import keyring
    backend = keyring.get_keyring()
    for item in getattr(backend, "backends", [backend]):
        if type(item).__module__.startswith(("keyring.backends.macOS", "keyring.backends.Windows",
                                             "keyring.backends.SecretService", "keyring.backends.libsecret",
                                             "keyring.backends.kwallet")):
            return item
    raise ValueError("无系统安全凭据库；请启用密钥环或在本地设置QILING_API_KEY")


def authorize(config, *, store=None, authorization=None):
    if store is None:
        store = secure_store()
    if authorization is None:
        from qiling_ai_sdk import QilingAuthorizationClient
        authorization = QilingAuthorizationClient(config["api_url"], client_name="脑洞动画工厂 brain-comic-plus 视频")
    result = authorization.authorize(on_authorization_url=lambda url: print("请在浏览器本人确认视频授权：" + url, flush=True))
    if result.get("status") != "authorized" or not result.get("api_key"):
        raise ValueError("视频授权未完成，未保存Key")
    store.set_password(KEY_SERVICE, config["api_url"], result["api_key"])
    return {"authorized": True, **config}


def api_client(config):
    key = os.getenv("QILING_API_KEY")
    if not key:
        try:
            key = secure_store().get_password(KEY_SERVICE, config["api_url"])
        except (ImportError, ValueError):
            key = None
    if not key:
        raise MissingApiKey("未配置API Key；先检查宿主videogen能力")
    from qiling_ai_sdk import QilingOpenClient
    return QilingOpenClient(config["api_url"], key, timeout=60)


def host_videogen_plan(storyboard, shot_id):
    """Hand off a fresh job for real host-tool discovery; this never submits video."""
    if job_path(storyboard, shot_id).exists():
        return dict(status="original_task_needs_credentials",
                    message="已有接口任务记录，先恢复原任务查询；不切换通道重复生成")
    payload = prepare(storyboard, shot_id)
    builtin = read(ROOT / "references/qiling-video.json")["builtin_videogen"]
    return dict(
        status="host_videogen_check_required",
        arguments=dict(prompt=payload["content"][0]["text"], model=builtin["model"],
                       duration=payload["duration"], aspect_ratio=payload["ratio"]),
        resolution_preference=builtin["resolution_preference"],
        reference_adapter_required=len(payload["content"]) > 1,
        message="检查实际可调用videogen及其参数；支持分辨率时尝试720p。"
                "有参考输入时先确认工具支持再传入，不能丢弃参考。"
                "异步提交后仅查询原任务；工具不可用时交付提示词走手动生成。"
                "这只是路由计划，尚未调用或生成视频。")


def prepare(storyboard, shot_id):
    document = read(storyboard)
    matches = [s for s in document["shots"] if s["id"] == shot_id]
    if len(matches) != 1:
        raise ValueError("分镜ID须存在且唯一")
    shot = matches[0]
    defaults = read(ROOT / "references/qiling-video.json")["generation_defaults"]
    options = {name: defaults[name] if shot.get(name) is None else shot[name]
               for name in ("duration", "resolution", "ratio", "generate_audio")}
    duration = options["duration"]
    if type(duration) is not int or not 4 <= duration <= 15:
        raise ValueError("单次视频长度须为4–15整数秒，长片请拆分")
    if options["resolution"] not in {"480p", "720p"}:
        raise ValueError("当前Mini接入只接受480p或720p")
    if options["ratio"] not in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}:
        raise ValueError("视频画幅不在已核实参数范围内")
    if type(options["generate_audio"]) is not bool:
        raise ValueError("generate_audio须明确为布尔值")
    styles = read(ROOT / "references/styles.json")
    style = next((s["prompt"] for s in styles["presets"] if s["id"] == document["style_id"]), None)
    if style is None:
        raise ValueError("未知style_id，不能自动换风格")
    template = shot["prompt_template"]
    refs = shot["references"]
    ids = [r["asset_id"] for r in refs]
    if len(ids) != len(set(ids)) or set(MARKER.findall(template)) != set(ids):
        raise ValueError("提示词引用与实际参考图不一致或ID重复")
    roles = [r["role"] for r in refs]
    if any(role not in {"reference_image", "first_frame", "last_frame"} for role in roles):
        raise ValueError("不支持的图片角色")
    if len(refs) > 30 or roles.count("first_frame") > 1 or roles.count("last_frame") > 1:
        raise ValueError("参考图片数量或首尾帧数量超限")
    if "last_frame" in roles and "first_frame" not in roles:
        raise ValueError("尾帧必须配合首帧")
    if "reference_image" in roles and any(r in roles for r in ("first_frame", "last_frame")):
        raise ValueError("当前接入不混合全模态参考与首尾帧模式")
    images = []
    for ref in refs:
        from PIL import Image
        path = Path(ref["file"])
        if not path.is_absolute():
            path = Path(storyboard).resolve().parent / path
        if path.stat().st_size >= 30 * 1024 * 1024:
            raise ValueError("单张参考图须小于30MB")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("参考图哈希变化，请重新检查分镜绑定")
        with Image.open(path) as picture:
            fmt = picture.format
            if getattr(picture, "n_frames", 1) != 1:
                raise ValueError("参考图须为静态图片")
            picture.verify()
        if fmt not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("参考图只接受静态PNG/JPEG/WebP")
        mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]
        images.append(dict(type="image_url", role=ref["role"],
                           image_url={"url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")}))
    slots = {asset_id: i + 1 for i, asset_id in enumerate(ids)}
    prompt = MARKER.sub(lambda match: f"@图片{slots[match[1]]}", template)
    if "{{" in prompt or "}}" in prompt or not prompt.strip():
        raise ValueError("提示词为空或有未解析标记")
    if style not in prompt:
        prompt = style + "\n" + prompt
    return dict(content=[dict(type="text", text=prompt), *images], **options)


def snapshot(result):
    data = result.get("data") or {}
    return {"call_id": result.get("id"), "remote_status": result.get("status"),
            "billing": result.get("billing"), "video_url": data.get("video_url"),
            "last_frame_url": data.get("last_frame_url")}


def summary(state):
    return {key: state.get(key) for key in ("status", "remote_status", "request_id", "call_id", "file", "sha256", "review", "billing")}


def download_video(url, destination):
    https_url(url)
    if not shutil.which("ffprobe"):
        raise ValueError("需要ffprobe验证视频；原任务已保留，补齐后只恢复下载")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=destination.parent, suffix=".mp4")
    try:
        # No API client or authorization header is sent to the media host.
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(url, timeout=60) as response:
            https_url(response.geturl())
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 1024 * 1024 * 1024:
                    raise ValueError("片段超过1GB，保留任务待核对")
                output.write(chunk)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", name],
                               capture_output=True, check=True, timeout=30)
        details = json.loads(probe.stdout)
        if not any(s.get("codec_type") == "video" for s in details["streams"]) or float(details["format"].get("duration", 0)) <= 0:
            raise ValueError("结果不包含可播放的视频")
        os.replace(name, destination)
        return details
    finally:
        if os.path.exists(name):
            os.unlink(name)


def job_path(storyboard, shot_id):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", shot_id):
        raise ValueError("分镜ID只使用字母、数字、连字符和下划线")
    return Path(storyboard).resolve().parent / "视频任务" / (shot_id + ".json")


def sync(state, path, client):
    if state["status"] == "downloaded":
        output = path.parent.parent / state["file"]
        if not output.is_file() or hashlib.sha256(output.read_bytes()).hexdigest() != state["sha256"]:
            raise ValueError("已下载片段缺失或改变；先核对原结果，不重新生成")
        return summary(state)
    if state.get("remote_status") != "succeeded" or not state.get("video_url"):
        if not state.get("call_id"):
            raise ValueError("提交结果未明；先按请求号核对，获得原调用号后用--call-id绑定")
        result = client.model_call(state["call_id"])
        if result.get("id") != state["call_id"]:
            raise ValueError("查询返回调用号与原任务不一致")
        if result.get("request_id") and result["request_id"] != state["request_id"]:
            raise ValueError("查询返回请求号与原任务不一致")
        state.update(snapshot(result))
        write(path, state)
    if state.get("remote_status") == "succeeded":
        if not state.get("video_url"):
            raise ValueError("任务成功但没有video_url，请核对原任务")
        output = path.parent.parent / "视频片段" / f"{path.stem}-{state['request_id']}.mp4"
        details = download_video(state["video_url"], output)
        state.update(status="downloaded", file=str(output.relative_to(path.parent.parent)),
                     sha256=hashlib.sha256(output.read_bytes()).hexdigest(), review="pending", probe=details)
        write(path, state)
    return summary(state)


def run(storyboard, shot_id, config, client, *, new_attempt=False, call_id=None, sync_only=False):
    path = job_path(storyboard, shot_id)
    with locked(path.with_suffix(".lock")):
        state = read(path) if path.exists() else None
        if state and state["api_url"] != config["api_url"]:
            raise ValueError("原任务属于另一个API地址，不能跨平台恢复")
        if call_id is not None:
            if not state or state.get("call_id") or new_attempt:
                raise ValueError("--call-id只能绑定已有未知任务，不能覆盖原调用号")
            result = client.model_call(call_id)
            if result.get("id") != call_id or result.get("request_id") != state["request_id"]:
                raise ValueError("该调用号未确认属于原请求，请在平台核实")
            state.update(snapshot(result), status="submitted")
            write(path, state)
            return sync(state, path, client)
        if sync_only:
            if not state:
                raise ValueError("没有原任务可查询")
            return sync(state, path, client)
        payload = prepare(storyboard, shot_id)
        signature = hashlib.sha256(json.dumps(dict(**config, **payload), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if state and new_attempt:
            if not (state["status"] in {"downloaded", "rejected"} or state.get("remote_status") in {"failed", "cancelled"}):
                raise ValueError("原任务未结束或待下载，不能创建新请求")
            write(path.parent / "历史任务" / (path.stem + "-" + state["request_id"] + ".json"), state)
            state = None
        if state:
            if state["signature"] != signature:
                raise ValueError("分镜内容已变；先用sync恢复原任务，确认结束后才能显式重做")
            return sync(state, path, client)
        state = dict(status="submitting", request_id="animation-" + uuid.uuid4().hex,
                     signature=signature, **config)
        write(path, state)
        try:
            result = client.video(model=config["model"], request_id=state["request_id"],
                                  idempotency_key=state["request_id"], **payload)
        except Exception as error:
            code = getattr(error, "status", getattr(error, "status_code", None))
            detail = getattr(error, "detail", None)
            known_id = detail.get("call_id") if isinstance(detail, dict) else None
            state.update(status="rejected" if code in {401, 402, 403} and not known_id else "unknown",
                         http_status=code, error_type=type(error).__name__, call_id=known_id)
            write(path, state)
            raise
        state.update(snapshot(result), status="submitted")
        write(path, state)
        if state.get("remote_status") == "succeeded":
            return sync(state, path, client)
        return summary(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("config", "authorize", "models"):
        commands.add_parser(name)
    for name in ("run", "sync"):
        command = commands.add_parser(name)
        command.add_argument("--storyboard", type=Path, required=True)
        command.add_argument("--id", required=True)
        if name == "run":
            command.add_argument("--new-attempt", action="store_true")
        command.add_argument("--call-id", type=int)
    args = parser.parse_args()
    try:
        config = settings()
        if args.command == "config":
            result = config
        elif args.command == "authorize":
            result = authorize(config)
        else:
            try:
                client = api_client(config)
            except MissingApiKey:
                if args.command == "run" and not args.new_attempt and args.call_id is None:
                    result = host_videogen_plan(args.storyboard, args.id)
                elif args.command in {"run", "sync"}:
                    result = dict(status="original_task_needs_credentials",
                                  message="恢复原任务需要对应凭据；不跨通道创建第二个视频")
                else:
                    result = dict(status="host_videogen_check_required",
                                  message="未配置API Key；检查宿主videogen，不要求先授权器灵")
            else:
                if args.command == "models":
                    model = client.model(config["model"])
                    docs = client.model_docs()
                    result = {"model": model, "documentation": [item for item in docs.get("items", []) if item.get("model") == config["model"]]}
                else:
                    result = run(args.storyboard, args.id, config, client,
                                 new_attempt=getattr(args, "new_attempt", False), call_id=args.call_id,
                                 sync_only=args.command == "sync")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("已中断；请先查询原视频任务。", file=sys.stderr)
    except Exception as error:
        # Upstream exceptions can echo secrets or base64 inputs; never print their bodies.
        message = str(error) if type(error) is ValueError else type(error).__name__
        print("视频操作未完成：" + message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
