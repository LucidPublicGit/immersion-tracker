"""Mokuro page breakdown uses submitted rows, never the reading baseline."""
from sqlalchemy.orm import Session

from app.db.models import LogEntry
from app.db.session import get_engine


def test_page_breakdown_counts_other_pushed_logs_only(client):
    with Session(get_engine()) as db:
        def add(volume, pages, amount, status):
            row = LogEntry(title='Vagabond', source='mokuro', content_type='manga',
                           source_ref=f'mokuro:{volume}:{pages}', amount=amount,
                           unit='comic_pages', tadoku_status=status,
                           notes=f'pages 32→196 (+{amount}); total=196; completed')
            db.add(row)
            db.flush()
            return row

        previous = add('volume17', 38, 32, 'pushed')
        current = add('volume17', 196, 164, 'pending')
        add('volume17', 190, 10, 'failed')
        add('volume18', 100, 100, 'pushed')
        db.commit()
        previous_id, current_id = previous.id, current.id

    row = client.get(f'/api/logs/{current_id}').json()
    assert row['mokuro_logged_pages'] == 32
    assert row['amount'] == 164
    queue = client.get('/api/queue').json()
    assert next(r for r in queue if r['id'] == current_id)['mokuro_logged_pages'] == 32

    with Session(get_engine()) as db:
        db.get(LogEntry, current_id).tadoku_status = 'pushed'
        db.commit()
    # History must not count this row twice after submission.
    row = client.get(f'/api/logs/{current_id}').json()
    assert row['mokuro_logged_pages'] == 32
    assert row['amount'] == 164
    assert client.get(f'/api/logs/{previous_id}').json()['mokuro_logged_pages'] == 164


def test_baseline_is_not_claimed_as_submitted(client):
    with Session(get_engine()) as db:
        row = LogEntry(title='Manga', source='mokuro', content_type='manga',
                       source_ref='mokuro:baseline:100', amount=20, unit='comic_pages',
                       tadoku_status='pending', notes='pages 80→100 (+20); total=196')
        db.add(row)
        db.commit()
        log_id = row.id
    data = client.get(f'/api/logs/{log_id}').json()
    assert data['mokuro_logged_pages'] == 0
    assert data['amount'] == 20
