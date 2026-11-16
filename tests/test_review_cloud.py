import base64
import io
import json
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import httpx

from noteflow import review_cloud
from noteflow.errors import NoteFlowError
from noteflow.review_audio import wav_bytes
from noteflow.review_cloud import CloudConfig, read_completion
from noteflow.process import Cancelled


def stream(text, finish="stop"):
    parts = [json.dumps({"choices": [{"index": 0, "delta": {"content": text[:10]}}]}, ensure_ascii=False),
             json.dumps({"choices": [{"index": 0, "delta": {"content": text[10:]}, "finish_reason": finish}]}, ensure_ascii=False),
             json.dumps({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}})]
    return ("\r\n\r\n".join("data: " + part for part in parts) + "\r\n\r\ndata: [DONE]\r\n\r\n").encode()


def test_sse_handles_split_utf8_usage_and_incomplete_generation():
    text = '{"status":"pass","summary":"音高一致","issues":[]}'
    raw = stream(text)
    result, usage = read_completion([raw[i:i + 7] for i in range(0, len(raw), 7)])
    assert result == text and usage["total_tokens"] == 130
    with pytest.raises(ValueError):
        read_completion([stream(text, "length")])
    with pytest.raises(ValueError):
        read_completion([b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'])


@pytest.mark.parametrize("url", ["http://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1?key=secret",
    "https://user@dashscope.aliyuncs.com/compatible-mode/v1",
    "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "https://api.example.com:99999/v1", "https://api.example.com\\@other.example.com/v1"])
def test_rejects_insecure_or_ambiguous_endpoint_urls(url):
    with pytest.raises(ValueError):
        CloudConfig(url, api_key="test-only").validate()


def test_custom_model_id_and_full_endpoint_are_accepted():
    config = CloudConfig("https://gateway.example.com/api/v1/chat/completions",
                         "provider/custom-audio-model", "test-only")
    config.validate()
    assert not config.dashscope
    assert config.endpoint == config.base_url


@pytest.fixture
def server(monkeypatch):
    captured, replies = [], []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))) )
            status, body, *delay = replies.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if delay:
                time.sleep(delay[0])
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *_):
            pass
    endpoint = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=endpoint.serve_forever, daemon=True)
    thread.start()
    original_client = httpx.AsyncClient
    async def local_endpoint(request):
        assert request.url.host == "dashscope.aliyuncs.com"
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=endpoint.server_port)
    monkeypatch.setattr(review_cloud.httpx, "AsyncClient", lambda **kw:
                        original_client(**kw, event_hooks={"request": [local_endpoint]}))
    try:
        yield captured, replies
    finally:
        endpoint.shutdown()
        endpoint.server_close()
        thread.join(timeout=3)


def test_http_sends_real_audio_and_uses_complete_stream(server):
    captured, replies = server
    replies.append((200, stream('{"status":"pass","summary":"一致","issues":[]}')))
    config = CloudConfig("https://dashscope.aliyuncs.com/compatible-mode/v1", api_key="test-only-secret")
    pcm = wav_bytes([0, 1000, -1000] * 100)
    text, usage = review_cloud.request(config, pcm, "复核音频")
    assert json.loads(text)["status"] == "pass" and usage["total_tokens"] == 130
    path, payload = captured[0]
    assert path == "/compatible-mode/v1/chat/completions" and payload["stream"] is True
    content = payload["messages"][0]["content"]
    decoded = base64.b64decode(content[0]["input_audio"]["data"].split(",", 1)[1])
    with wave.open(io.BytesIO(decoded)) as audio:
        assert audio.getnframes() == 300
    assert "test-only-secret" not in repr(config)
    assert payload["reasoning_effort"] == "none"


def test_generic_gateway_accepts_raw_base64_and_json_response(monkeypatch):
    endpoint = "https://gateway.example.com/api/v1/chat/completions"
    audio = wav_bytes([0, 1000, -1000] * 100)
    text = '{"status":"pass","summary":"一致","issues":[]}'

    def respond(request):
        assert str(request.url) == endpoint
        assert request.headers["Authorization"] == "Bearer test-only"
        payload = json.loads(request.content)
        assert payload["model"] == "vendor/listen-model"
        assert "enable_thinking" not in payload and "reasoning_effort" not in payload
        audio_part = payload["messages"][0]["content"][0]["input_audio"]
        assert audio_part == {"data": base64.b64encode(audio).decode(), "format": "wav"}
        return httpx.Response(200, json={
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"content": text}}],
            "usage": {"total_tokens": 25},
        })

    original_client = httpx.AsyncClient
    monkeypatch.setattr(review_cloud.httpx, "AsyncClient", lambda **kw:
                        original_client(**kw, transport=httpx.MockTransport(respond)))
    assert review_cloud.request(CloudConfig(endpoint, "vendor/listen-model", "test-only"), audio, "test") == (
        text, {"total_tokens": 25})


def test_does_not_follow_redirect_to_different_host(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request.url.host)
        return httpx.Response(307, headers={"Location": "https://other.example.com/v1/chat/completions"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(review_cloud.httpx, "AsyncClient", lambda **kw:
                        original_client(**kw, transport=httpx.MockTransport(respond)))
    with pytest.raises(NoteFlowError, match="307"):
        review_cloud.request(CloudConfig("https://gateway.example.com/v1", "audio-model", "test-only"),
                             wav_bytes([0]), "test")
    assert calls == ["gateway.example.com"]


def test_http_error_has_no_server_body_or_automatic_retry(server):
    captured, replies = server
    replies.append((429, b"secret response body"))
    config = CloudConfig("https://dashscope.aliyuncs.com/compatible-mode/v1", api_key="test-only")
    with pytest.raises(NoteFlowError) as caught:
        review_cloud.request(config, wav_bytes([0]), "test")
    assert len(captured) == 1 and "429" in str(caught.value) and "secret" not in str(caught.value)


def test_cancel_interrupts_an_idle_network_response(server):
    captured, replies = server
    replies.append((200, stream('{"status":"pass","summary":"","issues":[]}'), 3))
    flag = threading.Event()
    timer = threading.Timer(.3, flag.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(Cancelled):
            review_cloud.request(CloudConfig("https://dashscope.aliyuncs.com/compatible-mode/v1", api_key="test-only"),
                                wav_bytes([0]), "test", flag)
        assert time.monotonic() - start < 2
        assert len(captured) == 1
    finally:
        timer.cancel()
