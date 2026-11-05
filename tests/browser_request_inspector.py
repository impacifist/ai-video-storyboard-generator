"""Actual local HTTP preview/edit/compile/history flow; no external LLM calls."""

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from server import Handler  # noqa: E402
from storyboard import engine, library, providers  # noqa: E402
from conversion_fixtures import direction_output  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    artifacts = ROOT / 'storage/browser-check'
    artifacts.mkdir(parents=True, exist_ok=True)
    calls = []

    def fake(provider, model, system, user, schema):
        request = json.loads(user)
        calls.append((system, request, schema))
        return direction_output(request['plan'])

    try:
        with tempfile.TemporaryDirectory() as folder, patch.object(library, 'ROOT', Path(folder)), \
             patch.object(providers, 'load_settings', return_value={'OPENAI_API_KEY': 'fake', 'OPENAI_MODEL': 'mock'}), \
             patch.object(providers, 'generate_json', side_effect=fake), sync_playwright() as pw:
            brief = json.loads((ROOT / 'examples/rainy-classroom.json').read_text(encoding='utf-8'))
            doc = engine.generate({'brief': brief, 'provider': 'demo'})
            for shot, seconds in zip(doc['story']['shots'], [4, 4, 4, 5, 7, 6]):
                shot['duration'] = seconds
            doc['story']['shots'][3]['actions'] = ['Raise a hand.', 'Lower it after the reply.']
            board_id = library.save(doc)['id']
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1600, 'height': 1050})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('persona-storyboard.ui-language','ko')")
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.wait_for_function('config !== null')
                page.evaluate("async id => {await switchStudio('convert'); await loadSaved(id,true);}", board_id)
                page.locator('#video-family').select_option('minimax')
                page.locator('#conversion-auto-split').click()
                expect(page.locator('#conversion-plan-result h3')).to_contain_text('2개 클립')
                page.locator('#conversion-request-open').click()
                expect(page.locator('#request-segments .request-segment')).to_have_count(7)
                expect(page.locator('#request-segments')).to_contain_text('원본 시간 범위: 3–5초')
                assert not calls
                page.locator('#request-segments textarea').nth(3).fill('Raise the hand only. Do not lower it in this clip.')
                page.locator('#request-apply').click()
                expect(page.locator('#conversion-request')).not_to_be_visible()
                assert not calls
                expect(page.locator('#request-edit-status')).to_contain_text('수정 요청')
                page.locator('#conversion-consent').check()
                page.locator('#conversion-run').click()
                expect(page.locator('#notice')).to_contain_text('프롬프트를 변환해 보관')
                assert len(calls) == 1
                assert calls[0][1]['plan']['clips'][0]['shots'][-1]['segment_instruction'].startswith('Raise the hand only')
                assert library.load(board_id) == doc
                page.locator('.result-metadata summary').first.click()
                page.get_by_role('button', name='LLM 전송 이력·응답 보기', exact=True).first.click()
                expect(page.locator('#conversion-request')).to_be_visible()
                assert page.locator('#request-user').evaluate('e => e.readOnly')
                assert page.locator('#request-apply').is_hidden()
                expect(page.locator('#request-history-body')).to_contain_text('Raise the hand only')
                with page.expect_download() as downloaded:
                    page.locator('#request-download').click()
                target = artifacts / 'llm-request-history.json'
                downloaded.value.save_as(target)
                saved = json.loads(target.read_text(encoding='utf-8'))
                assert saved['request_trace'][0]['user'] == calls[0][1]
                assert 'output' in saved['request_trace'][0]
                page.locator('#request-close').click()
                page.locator('#conversion-request-open').click()
                expect(page.locator('#request-apply')).to_be_visible()
                for lang in ('en', 'ko', 'ja'):
                    page.evaluate('lang => I18n.select(lang)', lang)
                    for width in (390, 768, 1600):
                        page.set_viewport_size({'width': width, 'height': 1050})
                        assert page.locator('#conversion-request').evaluate('n => n.scrollWidth <= n.clientWidth + 1')
                    page.screenshot(path=str(artifacts / f'llm-request-{lang}.png'))
                page.evaluate("I18n.select('ko')")
                page.locator('#request-close').click()
                page.locator('#clip-limit').fill('10')
                page.locator('#conversion-consent').check()
                page.locator('#conversion-run').click()
                expect(page.locator('#notice')).to_contain_text('다시 불러오세요')
                assert len(calls) == 1
                page.locator('#conversion-request-open').click()
                expect(page.locator('#request-error')).to_contain_text('다시 불러오세요')
                page.locator('#request-reset').click()
                expect(page.locator('#request-error')).not_to_be_visible()
                assert page.evaluate('requestEdit') is None
                assert not errors, errors
                print('PASS: no-call request inspection, split offsets, segment edit, exact sent input/output history, JSON download, stale blocking, reset and 9 translated responsive layouts.')
            except Exception:
                page.screenshot(path=str(artifacts / 'request-failure.png'))
                raise
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    main()
