# 器灵 Seedance 2.0 Mini 视频

使用本技能的视频专用用户 API Key，不做软件授权码登录。直接使用完整文本通过器灵接口生成视频，不包含资产或参考图生成阶段。默认地址与平台模型名见 qiling-video.json。配置不包含 Key。

本页仅用于用户选择接口生成的情况。用户选择手动生成、已提供本地视频或只要提示词时，不运行本页授权、模型查询或生成命令；读取[手动生成与本地接续](local-video.md)。

## 无Key时先检查宿主能力

没有API Key时不把器灵授权作为生成视频的前提，先按[builtin-video.md](builtin-video.md)查找宿主实际可调用的videogen；存在时由宿主执行，默认seedance-2.0-fast、10秒、1:1，可设置分辨率时尝试720p。不存在时保留提示词并走手动生成，不假称具备工具。

脚本run在新任务无Key时返回host_videogen_check_required及候选参数，退出码为0；这是交给宿主检查并调用的路由计划，不是已提交或生成成功。脚本不能凭空调用宿主工具。已有视频任务时返回original_task_needs_credentials，先恢复原任务，不重复切换生成；显式authorize命令仅在用户选择授权时执行。

## 首次准备

复用宿主可用 Python 3.10+。脚本使用已核实的官方 `qiling-ai-sdk 0.5.4` 和系统 `keyring`；默认文生视频不需要Pillow，仅使用用户提供参考图时才需要。只补缺失依赖，不新建一套环境：

```sh
python -m pip install 'qiling-ai-sdk @ https://github.com/qilingAI/qiling-sdk-python/releases/download/v0.5.4/qiling_ai_sdk-0.5.4-py3-none-any.whl' 'keyring>=25,<26'
```

以下命令相对本技能目录，python 替换为实际可用解释器：

```sh
python scripts/qiling_video.py config
python scripts/qiling_video.py authorize
python scripts/qiling_video.py models
```

`authorize` 只打开 SDK 返回的 verification_url，由用户本人登录并确认。Key 存系统安全凭据库的 `brain-comic-plus:qiling-video`；没有安全凭据库时可由用户本地设置 `QILING_API_KEY`，不能把 Key 发到聊天或明文文件。`QILING_VIDEO_API_URL` 可指定已确认的平台根地址；不因授权响应或素材 URL 改变 API 地址，不自动搜其他工程凭据。

`models` 只读当前模型目录与动态文档，核实启用状态、参考图支持、请求 schema、时长、画幅和分辨率。开发时的公开文档请求返回401，已有项目缓存列出4–15秒、480p/720p；**缓存是起点，实际调用前须授权后核对实时数据**。不要直接照搬其他平台、完整版或 Fast 的参数。脚本先按已知4–15秒等范围保守验证；接口或实时文档变更时修正后再调用，不通过换模型绕过。

统一默认参数定义在qiling-video.json的generation_defaults：duration=10、resolution=480p、ratio=1:1、generate_audio=true。接口分镜与手动交接按此填写；内置通道读取builtin_videogen，不覆盖generation_defaults；执行脚本对缺失或null的字段使用同一默认值。用户明确指定其他受支持参数时才覆盖，不自动选15秒、720p或9:8。画面与对白、动作音效、环境声统一生成，有对白配字幕，一般无旁白；BGM可选且后期加入。参数和后期安排留在制作说明，不拼进模型提示词。后期仅用FFmpeg，不调用Seedance合成。

## 提交、查询与恢复

```sh
python scripts/qiling_video.py run --storyboard /实际路径/分镜提示词.json --id shot-01
```

默认references为空数组，content只包含完整文本，不上传图片、不生成参考图。脚本直接提交人物、场景、动作、运镜、对白与音效要求，保持一次请求生成整条短片。

用户明确提供参考图时才启用可选传图：按实际顺序替换{{ref:ID}}为@图片N，核对文件及哈希，将图片编码为Data URI随content上传。不得为此自动建立资产库；不同时传prompt/reference_images等便捷字段，不把本机路径当远程地址。

首次 run 提交一次，返回 queued/running 时保留调用号。稍后重跑同一命令只查询原 `call_id`；不内部长时间等待。成功且包含 video_url 时下载真实视频，下载失败重跑只恢复下载。下载不带 API Key 到素材服务器。任务记录在分镜JSON旁的 `视频任务/`，结果在 `视频片段/`。

文稿或参考图已修改时，先用 `python scripts/qiling_video.py sync --storyboard /实际路径/分镜提示词.json --id shot-01` 查询原任务；sync不读取或提交新分镜。需要绑定未知提交的原调用号时，在该命令后加 `--call-id 原数字调用号`；脚本会核对平台返回的request_id，不能覆盖已有调用号。

网络异常、进程中断、HTTP错误或缺失调用号时保留请求号，不自动再次POST。已有调用号则用 run 查询；提交时没有收到调用号的未知结果先到平台按请求号核对。取得真实调用号后使用 `--call-id` 绑定原任务，再用 run 恢复，不制造新请求。只有原任务已明确完成、失败或取消，并且用户确实要求重做时，使用 `--new-attempt`；保留历史请求，不删除记录绕过保护。

状态只有 `succeeded` 才表示服务端完成，仍需本地下载与逐段检查。`queued/running/cancel_requested` 查询原任务；`unknown/review` 不能当成功。费用保存返回的 billing 原值，null 不等于免费，不额外扣普通软件次数额度。

## 合同与验证边界

SDK `video()` 对应 POST `/v1/videos`，`model_call()` 对应 GET `/v1/model-calls/{call_id}`。返回顶层 `id/status/billing` 和 `data.video_url`；请求号在调用前落盘，用 `request_id` 与 `Idempotency-Key` 固定同一任务。SDK默认生成请求不做自动重试。

401处理Key，402处理余额，403处理权限，400/422处理参数；不自动充值、付款、切模型或切账户。本轮接入仅运行模拟接口验证，不为验证生成付费视频，也不提前启动用户浏览器授权。

接口依据：[器灵官方SDK v0.5.4](https://github.com/qilingAI/qiling-sdk-python/releases/tag/v0.5.4)、[器灵公开文档索引](https://867fas1f7s.apifox.cn/llms.txt)。2026-10-27接入实现已对照本机官方0.5.4 SDK方法及项目缓存动态文档；实时权限与真实生成效果要在用户实际创作时验证。
