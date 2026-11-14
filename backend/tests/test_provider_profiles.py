import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime


@pytest.mark.parametrize('capability,provider,model', [
    ('text', 'bailian', 'qwen-plus'),
    ('image', 'bailian-image', 'wan2.6-image'),
    ('video', 'compshare-h3', 'MiniMax-H3'),
])
async def test_model_ids_trim_paste_whitespace_and_reject_blank(capability, provider, model):
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        path = f'/api/provider-config/profiles/{capability}/production'
        payload = {
            'provider': provider, 'model': f' {model} \n',
            'baseUrl': 'https://provider.test/api/v1', 'timeoutMs': 180000,
            'apiKey': 'offline', 'enabled': True,
        }
        response = await client.put(path, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['model'] == model
        assert runtime.provider_config_store.get_media(capability)['model'] == model
        payload['model'] = ' \t\n '
        refused = await client.put(path, json=payload)
        assert refused.status_code == 400, refused.text
        assert runtime.provider_config_store.get_media(capability)['model'] == model


@pytest.mark.parametrize(
    "capability,prod_provider,test_provider,prod_model,test_model",
    [
        ("video", "compshare-h3", "bailian-video", "MiniMax-H3", "wan2.2-i2v-flash"),
        ("image", "bailian-image", "bailian-image", "wanx2.1-t2i-plus", "wan2.2-t2i-flash"),
        ("text", "bailian", "openai-compatible", "qwen-plus", "test-model"),
    ],
)
async def test_profiles_save_switch_clear_without_generation(
    capability,
    prod_provider,
    test_provider,
    prod_model,
    test_model,
):
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        root = "/api/provider-config/profiles/" + capability
        production = {
            "provider": prod_provider,
            "model": prod_model,
            "baseUrl": "https://production.test",
            "apiKey": "prod-key",
            "enabled": True,
            "timeoutMs": 60000,
        }
        testing = {
            **production,
            "provider": test_provider,
            "model": test_model,
            "baseUrl": "https://testing.test",
            "apiKey": "test-key",
            "resolution": "480P",
        }
        assert (await client.put(root + "/production", json=production)).status_code == 200
        saved = await client.put(root + "/test", json=testing)
        assert saved.status_code == 200, saved.text
        view = (await client.get("/api/provider-config")).json()
        assert view[capability]["model"] == prod_model
        assert view["profiles"][capability]["active"] == "production"
        assert "prod-key" not in str(view) and "test-key" not in str(view)
        assert (await client.post(root + "/test/activate")).status_code == 200
        assert (await client.get("/api/provider-config")).json()[capability]["model"] == test_model
        assert (await client.post(root + "/production/activate")).status_code == 200
        assert (await client.get("/api/provider-config")).json()[capability]["model"] == prod_model
        assert (await client.delete(root + "/test")).status_code == 204
        assert (await client.post(root + "/test/activate")).status_code == 409
        assert (await client.get("/api/provider-config")).json()[capability]["model"] == prod_model


async def test_profile_cannot_reuse_secret_across_hosts_or_protocols():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        root = "/api/provider-config/profiles/video/production"
        payload = {
            "provider": "compshare-h3",
            "model": "MiniMax-H3",
            "baseUrl": "https://production.test",
            "apiKey": "secret",
            "enabled": True,
            "timeoutMs": 60000,
        }
        assert (await client.put(root, json=payload)).status_code == 200
        payload.pop("apiKey")
        assert (await client.put(root, json=payload)).status_code == 200
        payload["baseUrl"] = "https://other.test"
        assert (await client.put(root, json=payload)).status_code == 409
        view = (await client.get("/api/provider-config")).json()
        assert view["video"]["baseUrl"] == "https://production.test"
        assert "secret" not in str(view)
        payload['baseUrl'] = 'http://production.test'
        assert (await client.put(root, json=payload)).status_code == 409


async def test_h3_switch_back_uses_current_text_writer_and_invalid_profile_is_atomic():
    from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
    from comicflow.providers.minimax_h3 import MinimaxH3Provider

    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        root = "/api/provider-config/profiles/"
        shared = {"apiKey": "offline", "enabled": True, "timeoutMs": 60000}
        text = {
            **shared,
            "provider": "bailian",
            "model": "qwen-plus",
            "baseUrl": "https://text.test/v1",
        }
        assert (await client.put(root + "text/production", json=text)).status_code == 200
        prod = {
            **shared,
            "provider": "compshare-h3",
            "model": "MiniMax-H3",
            "baseUrl": "https://h3.test",
        }
        assert (await client.put(root + "video/production", json=prod)).status_code == 200
        testing = {
            **shared,
            "provider": "bailian-video",
            "model": "wan2.2-i2v-flash",
            "baseUrl": "https://wan.test/api/v1",
        }
        assert (await client.put(root + "video/test", json=testing)).status_code == 200
        await client.post(root + "video/test/activate")
        assert isinstance(runtime.pipeline._dynamic_visual_provider, BailianImageToVideoProvider)
        rejected = await client.put(root + "video/test", json={**testing, "generationType": "t2v"})
        assert rejected.status_code == 400
        assert runtime.provider_config_store.get_media("video")["generationType"] == "i2v"
        await client.post(root + "video/production/activate")
        provider = runtime.pipeline._dynamic_visual_provider
        assert isinstance(provider, MinimaxH3Provider)
        assert provider._prompt_writer is not None
        assert provider._prompt_writer._complete.__self__ is runtime.pipeline._text_provider
