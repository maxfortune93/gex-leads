# Pipeline de ingestão de leads

API (FastAPI) recebe webhook criptografado → valida → publica em `lead.received` (RabbitMQ) →
worker grava cliente/pedido/evento no MySQL em uma transação. Falhas definitivas vão para `lead.dead.processing_failed`.

## Requisitos
Docker + Docker Compose. Para os testes locais: Python 3.10+.

## Subir
```bash
cp .env.example .env
docker compose up -d --build        # mysql, rabbitmq, api (:8000), worker
python3 tools/send_dataset.py       # envia o dataset
```
RabbitMQ Management: http://localhost:15672 (usuário/senha do `.env`).

## Testar
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest                              # unitários (sem infra)
RUN_INTEGRATION=1 pytest            # + fluxo real (com `docker compose up` rodando)
```
Query de auditoria: `sql/audit_query.sql` (comparável a `data/expected_summary.csv`).

## Premissas
1. `transaction_id + event` é a chave de idempotência; `UNIQUE KEY` no MySQL é o lock entre processos.
2. A API publica com a linha travada (`SELECT … FOR UPDATE`) e só confirma (`commit`) após o publisher confirm; falha → rollback, 503 e retry seguro.
3. Entrega at-least-once: se o commit falhar após publicar, o retry republica; o worker é idempotente (`UNIQUE` em `orders.transaction_id` e `order_events(order_id, event)`).
4. Retry do worker: republica na mesma fila com header `x-attempt` (máx. 3); depois DLQ com mensagem original, `correlation_id`, tentativas e erro.
5. Mensagem ilegível vai direto à DLQ; o país do pedido é o `customer.country`.
