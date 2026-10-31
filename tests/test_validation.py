"""잘못된 OCR 결과가 저장되거나 휴무로 오인되지 않는지 확인한다."""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import ocr
import source_nl

@pytest.mark.parametrize('result', [None, {}, {'days': {}}, {'days': {'2026-02-30': [{}]}}, {'days': {'20261020': [{}]}}, {'days': {'2026-10-20': []}}, {'days': {'2026-10-20': [{'items': '쌀밥'}]}}, {'days': {'2026-10-20': [{'items': [None]}]}}, {'days': {'2026-10-20': [{'items': [], 'closed': 'false'}]}}])
def test_reject_invalid_results(result):
    with pytest.raises(ValueError):
        ocr._normalize(result)

def test_missing_menu_is_not_closed():
    assert source_nl._meal('중식', '')['closed'] is False
    result = ocr._normalize({'days': {'2026-10-20': [{'items': []}]}})
    assert result['days']['2026-10-20'][0]['closed'] is False

def test_compare_closed_state():
    a = ocr._normalize({'days': {'2026-10-20': [{'items': [], 'closed': True}]}})
    b = ocr._normalize({'days': {'2026-10-20': [{'items': [], 'closed': False}]}})
    assert ocr.diff(a, b) == ['2026-10-20 식사']

def test_review_changes_mark_new_dates_disputed():
    def result(a, b):
        return ocr._normalize({'days': {'2026-10-20': [{'items': [a]}], '2026-10-21': [{'items': [b]}]}})
    with patch.object(ocr, 'available', return_value=True), patch.object(ocr, '_ask', side_effect=[result('밥', '국'), result('빵', '국'), result('밥', '죽')]):
        final = ocr.transcribe(b'image', 'image/png', '')
    assert not final['verified']
    assert final['disputed'] == ['2026-10-20 식사', '2026-10-21 식사']
