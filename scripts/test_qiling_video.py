import base64
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from qiling_ai_sdk import QilingOpenClient

from qiling_video import (KEY_SERVICE, MissingApiKey, api_client, authorize, download_video,
                          host_videogen_plan, job_path, main, read, run, secure_store, write)


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.topic = Path(self.temp.name)
        self.image = self.topic / "角色.png"
        Image.new("RGB", (16, 12), "red").save(self.image)
        self.book = self.topic / "分镜提示词.json"
        self.config = dict(api_url="https://platform.invalid", model="doubao-seedance-2.0-mini")
        self.shot = dict(id="shot-01", title="测试", duration=8, resolution="720p", ratio="16:9",
                         generate_audio=True, prompt_template="{{ref:C01}}为角色参考。0–8秒，缓推，主角停步。无背景配乐。",
                         references=[dict(asset_id="C01", file=str(self.image), role="reference_image",
                                          sha256=hashlib.sha256(self.image.read_bytes()).hexdigest())])
        self.save_book()
        self.client = QilingOpenClient(self.config["api_url"], "test-video-key")
        self.http = self.client._http._request = Mock(return_value=dict(id=17, status="queued", billing=None))
        self.journal = job_path(self.book, "shot-01")

    def save_book(self):
        write(self.book, dict(style_id="chinese-handdrawn-animation", shots=[self.shot]))

    def run_clip(self, **options):
        return run(self.book, "shot-01", self.config, self.client, **options)

    def fake_download(self, url, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mock-generated-video")
        return dict(format=dict(duration="8.0"), streams=[dict(codec_type="video")])

    def success(self):
        return dict(id=17, status="succeeded", data=dict(video_url="https://cdn.invalid/result.mp4"), billing=dict(fee="1.23"))

    def test_sdk_payload_has_real_image_and_stable_request(self):
        self.run_clip()
        args, kwargs = self.http.call_args
        self.assertEqual(args[:2], ("POST", "/v1/videos"))
        payload = args[2]
        self.assertEqual(payload["model"], "doubao-seedance-2.0-mini")
        self.assertEqual(payload["request_id"], kwargs["extra_headers"]["Idempotency-Key"])
        self.assertEqual(kwargs["extra_headers"]["Authorization"], "Bearer test-video-key")
        self.assertFalse(kwargs["auth"])
        self.assertNotIn("prompt", payload)
        self.assertNotIn("reference_images", payload)
        self.assertIn("@图片1", payload["content"][0]["text"])
        self.assertIn("工笔重彩", payload["content"][0]["text"])
        image = payload["content"][1]
        self.assertEqual(image["role"], "reference_image")
        self.assertEqual(base64.b64decode(image["image_url"]["url"].split(",", 1)[1]), self.image.read_bytes())
        log = self.journal.read_text()
        self.assertNotIn("test-video-key", log)
        self.assertNotIn("base64", log)

    def test_text_only_video_needs_no_images_or_pillow(self):
        self.shot["references"] = []
        self.shot["prompt_template"] = "主角停步，抬手推门。对白：开门。声音：脚步与叩门声。"
        self.save_book()
        with patch.dict("sys.modules", {"PIL": None}):
            self.run_clip()
        payload = self.http.call_args.args[2]
        self.assertEqual(len(payload["content"]), 1)
        self.assertEqual(payload["content"][0]["type"], "text")
        self.assertIn("对白：开门", payload["content"][0]["text"])
        self.assertTrue(payload["generate_audio"])
        self.assertNotIn("reference_images", payload)

    def test_unspecified_duration_submits_ten_seconds(self):
        del self.shot["duration"]
        self.save_book()
        self.run_clip()
        self.assertEqual(self.http.call_args.args[2]["duration"], 10)

    def test_missing_generation_parameters_use_shared_defaults(self):
        for name in ("duration", "resolution", "ratio", "generate_audio"):
            del self.shot[name]
        self.save_book()
        self.run_clip()
        payload = self.http.call_args.args[2]
        self.assertEqual({name: payload[name] for name in ("duration", "resolution", "ratio", "generate_audio")},
                         dict(duration=10, resolution="480p", ratio="1:1", generate_audio=True))

    def test_null_generation_parameters_use_shared_defaults(self):
        self.shot.update(duration=None, resolution=None, ratio=None, generate_audio=None)
        self.save_book()
        self.run_clip()
        payload = self.http.call_args.args[2]
        self.assertEqual((payload["duration"], payload["resolution"], payload["ratio"], payload["generate_audio"]),
                         (10, "480p", "1:1", True))

    def test_explicit_supported_parameters_override_defaults(self):
        self.shot.update(duration=15, resolution="720p", ratio="16:9", generate_audio=False)
        self.save_book()
        self.run_clip()
        payload = self.http.call_args.args[2]
        self.assertEqual((payload["duration"], payload["resolution"], payload["ratio"], payload["generate_audio"]),
                         (15, "720p", "16:9", False))

    def test_no_key_does_not_require_api_sdk(self):
        store = Mock()
        store.get_password.return_value = None
        with patch.dict("os.environ", {"QILING_API_KEY": ""}), \
                patch("qiling_video.secure_store", return_value=store), \
                patch.dict("sys.modules", {"qiling_ai_sdk": None}):
            with self.assertRaises(MissingApiKey):
                api_client(self.config)

    def test_builtin_plan_uses_fast_model_and_host_parameter_names(self):
        self.shot.update(references=[], prompt_template="主角抬手推门。", duration=10, ratio="1:1")
        self.save_book()
        plan = host_videogen_plan(self.book, "shot-01")
        self.assertEqual(plan["status"], "host_videogen_check_required")
        self.assertEqual(plan["arguments"]["model"], "seedance-2.0-fast")
        self.assertEqual(plan["arguments"]["duration"], 10)
        self.assertEqual(plan["arguments"]["aspect_ratio"], "1:1")
        self.assertNotIn("ratio", plan["arguments"])
        self.assertNotIn("resolution", plan["arguments"])
        self.assertEqual(plan["resolution_preference"], "720p")
        self.assertFalse(plan["reference_adapter_required"])
        self.assertFalse(self.journal.exists())
        self.http.assert_not_called()

    def test_existing_api_task_never_falls_back_to_builtin(self):
        self.run_clip()
        before = self.journal.read_bytes()
        plan = host_videogen_plan(self.book, "shot-01")
        self.assertEqual(plan["status"], "original_task_needs_credentials")
        self.assertNotIn("arguments", plan)
        self.assertEqual(before, self.journal.read_bytes())
        self.assertEqual(self.http.call_count, 1)

    def test_no_key_cli_returns_host_handoff_with_zero_exit(self):
        self.shot.update(references=[], prompt_template="主角抬手推门。")
        self.save_book()
        output = io.StringIO()
        argv = ["qiling_video.py", "run", "--storyboard", str(self.book), "--id", "shot-01"]
        with patch("sys.argv", argv), patch("qiling_video.api_client", side_effect=MissingApiKey), redirect_stdout(output):
            code = main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "host_videogen_check_required")
        self.http.assert_not_called()

    def test_builtin_plan_keeps_reference_adapter_requirement(self):
        plan = host_videogen_plan(self.book, "shot-01")
        self.assertTrue(plan["reference_adapter_required"])
        self.http.assert_not_called()

    def test_rerun_only_queries_original_task_and_preserves_fee(self):
        self.run_clip()
        self.http.return_value = self.success()
        with patch("qiling_video.download_video", side_effect=self.fake_download):
            result = self.run_clip()
        self.assertEqual([call.args[:2] for call in self.http.call_args_list],
                         [("POST", "/v1/videos"), ("GET", "/v1/model-calls/17")])
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["review"], "pending")
        self.assertEqual(result["billing"]["fee"], "1.23")
        self.assertEqual(self.run_clip(), result)
        self.assertEqual(self.http.call_count, 2)

    def test_download_failure_resumes_download_without_new_request(self):
        self.http.return_value = self.success()
        with patch("qiling_video.download_video", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.run_clip()
        with patch("qiling_video.download_video", side_effect=self.fake_download):
            result = self.run_clip()
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(self.http.call_count, 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local FFmpeg")
    def test_download_verifies_real_video_and_sends_no_credentials(self):
        source = self.topic / "local.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32:d=0.2",
                        "-an", "-c:v", "libx264", str(source)], check=True, capture_output=True)
        response = io.BytesIO(source.read_bytes())
        response.geturl = lambda: "https://cdn.invalid/video.mp4"
        output = self.topic / "download" / "result.mp4"
        with patch("qiling_video.urllib.request.urlopen", return_value=response) as fetch:
            details = download_video("https://cdn.invalid/video.mp4", output)
        self.assertTrue(output.is_file())
        self.assertTrue(any(s["codec_type"] == "video" for s in details["streams"]))
        fetch.assert_called_once_with("https://cdn.invalid/video.mp4", timeout=60)

    def test_success_without_url_keeps_querying_original_task(self):
        self.http.return_value = dict(id=17, status="succeeded", data={})
        with self.assertRaises(ValueError):
            self.run_clip()
        self.http.return_value = self.success()
        with patch("qiling_video.download_video", side_effect=self.fake_download):
            result = self.run_clip()
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual([c.args[0] for c in self.http.call_args_list], ["POST", "GET", "GET"])

    def test_uncertain_submit_blocks_retry_and_new_attempt(self):
        self.http.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            self.run_clip()
        for kwargs in ({}, {"new_attempt": True}):
            with self.assertRaises(ValueError):
                self.run_clip(**kwargs)
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(read(self.journal)["status"], "unknown")
        self.assertTrue(read(self.journal)["request_id"])

    def test_can_bind_only_verified_original_request(self):
        self.http.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            self.run_clip()
        self.http.side_effect = None
        self.http.return_value = dict(id=17, status="running", request_id="wrong-request")
        with self.assertRaises(ValueError):
            self.run_clip(call_id=17)
        self.assertIsNone(read(self.journal).get("call_id"))
        request_id = read(self.journal)["request_id"]
        self.http.return_value = dict(id=17, status="running", request_id=request_id)
        result = self.run_clip(call_id=17)
        self.assertEqual(result["call_id"], 17)
        self.assertEqual(sum(call.args[0] == "POST" for call in self.http.call_args_list), 1)

    def test_changed_prompt_cannot_resubmit_pending_job(self):
        self.run_clip()
        self.shot["prompt_template"] += "主角转身。"
        self.save_book()
        with self.assertRaises(ValueError):
            self.run_clip()
        self.assertEqual(self.http.call_count, 1)
        self.run_clip(sync_only=True)
        self.assertEqual(self.http.call_args.args[:2], ("GET", "/v1/model-calls/17"))

    def test_reference_tampering_and_invalid_roles_fail_before_network(self):
        for change in (dict(sha256="0" * 64), dict(role="last_frame")):
            original = self.shot["references"][0].copy()
            self.shot["references"][0].update(change)
            self.save_book()
            with self.assertRaises(ValueError):
                self.run_clip()
            self.shot["references"][0] = original
        self.http.assert_not_called()

    def test_total_length_cannot_be_sent_as_20_second_single_call(self):
        self.shot["duration"] = 20
        self.save_book()
        with self.assertRaises(ValueError):
            self.run_clip()
        self.http.assert_not_called()

    def test_explicit_redo_of_finished_clip_archives_original(self):
        self.http.return_value = self.success()
        with patch("qiling_video.download_video", side_effect=self.fake_download):
            first = self.run_clip()
            second = self.run_clip(new_attempt=True)
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertEqual(len(list((self.journal.parent / "历史任务").glob("*.json"))), 1)
        self.assertTrue((self.topic / first["file"]).is_file())

    def test_authorization_is_separate_and_never_exposes_key(self):
        store, auth = Mock(), Mock()
        auth.authorize.return_value = dict(status="authorized", api_key="private-video-key", base_url="https://other.invalid")
        result = authorize(self.config, store=store, authorization=auth)
        store.set_password.assert_called_once_with(KEY_SERVICE, self.config["api_url"], "private-video-key")
        self.assertNotIn("private-video-key", json.dumps(result))
        self.assertEqual(result["api_url"], self.config["api_url"])
        auth.authorize.return_value = dict(status="denied")
        store.reset_mock()
        with self.assertRaises(ValueError):
            authorize(self.config, store=store, authorization=auth)
        store.set_password.assert_not_called()

    def test_rejects_plaintext_keyring(self):
        insecure = type("Insecure", (), {})()
        type(insecure).__module__ = "keyrings.alt.file"
        keyring = Mock()
        keyring.get_keyring.return_value = insecure
        with patch.dict("sys.modules", {"keyring": keyring}):
            with self.assertRaises(ValueError):
                secure_store()


if __name__ == "__main__":
    unittest.main()
