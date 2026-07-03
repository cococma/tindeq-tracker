"""Data access for coach conversations and recommendations."""

import json

from psycopg2.extras import RealDictCursor


def create_conversation(conn, title=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO coach_conversations (title) VALUES (%s) RETURNING id",
            (title,),
        )
        cid = cur.fetchone()[0]
    conn.commit()
    return cid


def list_conversations(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT c.*, COUNT(m.id) AS n_messages, MAX(m.created_at) AS last_message_at
            FROM coach_conversations c
            LEFT JOIN coach_messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY COALESCE(MAX(m.created_at), c.created_at) DESC
            """
        )
        return cur.fetchall()


def get_messages(conn, conversation_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT role, content, created_at FROM coach_messages WHERE conversation_id = %s ORDER BY id",
            (conversation_id,),
        )
        return cur.fetchall()


def add_message(conn, conversation_id, role, content):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO coach_messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conversation_id, role, content),
        )
        cur.execute(
            "UPDATE coach_conversations SET updated_at = NOW() WHERE id = %s",
            (conversation_id,),
        )
    conn.commit()


def save_recommendation(conn, snapshot, constraint_text, recommendation, model):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO coach_recommendations (context_snapshot, constraint_text, recommendation, model)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (json.dumps(snapshot, default=str), constraint_text, recommendation, model),
        )
        rid = cur.fetchone()[0]
    conn.commit()
    return rid


def list_recommendations(conn, limit=10):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, created_at, constraint_text, recommendation, model FROM coach_recommendations ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return cur.fetchall()
