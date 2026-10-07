# Teste Técnico Backend Sênior

## Objetivo

Construa uma pequena esteira de ingestão de leads.

O sistema deve receber um webhook criptografado, validar os dados, evitar duplicidade, publicar o evento em uma fila e persistir o lead por meio de um worker.

Queremos avaliar como você trata concorrência, falhas, consistência de dados e testes. Não esperamos uma plataforma completa.

| Item | Definição |
|---|---|
| Prazo | 48 horas após o recebimento |
| Esforço esperado | 8 a 12 horas |
| Linguagem | Python ou Go |
| Entrega | Repositório Git |
| Infraestrutura | MySQL 8 e RabbitMQ |

## O que você recebeu

- `data/webhook_payloads.json`: 36 requisições de teste.
- `data/grummer_secret.txt`: chave AES-256 em hexadecimal.
- `data/expected_results.json`: totais esperados após processar todo o dataset.
- `data/expected_summary.csv`: total de leads aceitos por país e produto.
- `docker-compose.yml`: MySQL e RabbitMQ prontos para uso.
- `.env.example`: configuração local sugerida.
- `tools/send_dataset.py`: script opcional para enviar o dataset para sua API.

## Fluxo esperado

1. A API recebe `POST /webhooks/grummer`.
2. A requisição bruta é salva para auditoria.
3. O payload é decriptado e validado.
4. Eventos repetidos são identificados sem condição de corrida.
5. Vendas aprovadas são publicadas na fila `lead.received`.
6. Um worker consome a fila e grava os dados no MySQL dentro de uma transação.
7. Falhas temporárias são tentadas novamente.
8. Falhas definitivas vão para `lead.dead.processing_failed`.

## Formato da requisição

O header abaixo indica que o body está criptografado:

```text
X-GR-Encrypted: true
```

O body recebido pela API tem este formato:

```json
{
  "iv": "base64",
  "ciphertext": "base64"
}
```

Use:

- AES-256-CBC.
- PKCS7 padding.
- A chave hexadecimal de `data/grummer_secret.txt`.
- O IV informado em cada requisição.

Depois da decriptação, o resultado é um objeto JSON com estes campos obrigatórios:

| Campo | Regra |
|---|---|
| `transaction_id` | Texto não vazio |
| `transaction_time` | Data e hora ISO 8601 com timezone |
| `event` | Tipo do evento |
| `customer.email` | E-mail do cliente |
| `customer.first_name` | Pode estar vazio |
| `customer.phone` | Telefone do cliente |
| `customer.country` | Código ISO de duas letras |
| `product.id` | Identificador do produto |
| `product.name` | Nome do produto |
| `payment.amount_usd` | Número maior que zero |
| `payment.status` | Status do pagamento |

## Normalização

Antes de publicar:

- E-mail: remover espaços nas pontas, converter para minúsculas e validar o formato.
- Telefone: remover espaços, parênteses e hífens. Aceitar `+` somente no início. Depois da limpeza, exigir entre 8 e 15 dígitos.
- Nome: usar `Customer` quando estiver vazio.
- País: converter para maiúsculas.

E-mail ou telefone inválido deve ser tratado como schema inválido.

## Respostas da API

| Situação | HTTP | Body mínimo |
|---|---:|---|
| Venda aprovada aceita | `202` | `{"status":"accepted"}` |
| Evento duplicado | `200` | `{"status":"duplicate"}` |
| Evento válido, mas não aprovado | `200` | `{"status":"ignored"}` |
| Falha de decriptação | `400` | `{"status":"decrypt_failed"}` |
| Schema inválido | `422` | `{"status":"schema_failed"}` |
| Banco ou RabbitMQ indisponível | `503` | `{"status":"unavailable"}` |

Todas as requisições devem gerar um `correlation_id` UUID. Retorne esse valor no header `X-Correlation-ID` e use o mesmo valor nos logs e na mensagem publicada.

## Idempotência e concorrência

A chave natural é:

```text
transaction_id + event
```

Requisitos:

- A mesma chave só pode ser publicada uma vez.
- Duas requisições simultâneas com a mesma chave não podem criar dois eventos.
- O controle deve funcionar entre processos diferentes. Um lock apenas em memória não resolve.
- A entrega bruta pode ser registrada novamente para auditoria, mas o evento de negócio não pode ser duplicado.
- Se a publicação no RabbitMQ falhar, a API deve retornar `503` e permitir uma nova tentativa segura. Não marque o evento como publicado antes de ele ser realmente publicado.

## Regras de roteamento

Publique em `lead.received` somente quando:

```text
event == "order.approved"
payment.status == "approved"
```

Eventos válidos que não atendem a essas duas condições devem ser registrados como ignorados e não devem ir para a fila.

Falhas de decriptação e schema devem ser registradas na auditoria e não devem ir para a fila.

## Worker

O worker consome `lead.received` e persiste o evento.

Requisitos:

- Persistir cliente, pedido e evento dentro de uma transação MySQL.
- Garantir idempotência também no worker. Redelivery não pode duplicar dados.
- Confirmar a mensagem no RabbitMQ somente depois do commit.
- Fazer até três tentativas no total para falhas temporárias.
- Depois da última falha, publicar em `lead.dead.processing_failed`.
- A mensagem da DLQ deve conter a mensagem original, `correlation_id`, total de tentativas e resumo do erro.

Você pode escolher nomes e estrutura das tabelas. No mínimo, precisamos conseguir consultar:

- Requisições brutas e resultado do processamento.
- Clientes.
- Pedidos.
- Eventos dos pedidos.

## Logs

Produza logs estruturados em JSON com, quando aplicável:

- `correlation_id`.
- `transaction_id`.
- `event`.
- etapa do processamento.
- resultado.
- duração.

Nunca grave e-mail, telefone, chave AES ou payload decriptado completo nos logs.

## Query de auditoria

Entregue `sql/audit_query.sql` com uma query que mostre a quantidade de vendas aprovadas e persistidas, agrupada por:

- país;
- produto.

O resultado deve poder ser comparado com `data/expected_summary.csv`.

## Testes obrigatórios

Inclua testes automatizados para, no mínimo:

- Payload válido e criptografado.
- Falha de decriptação.
- Schema inválido.
- Duplicidade sequencial e simultânea.
- Redelivery no worker sem duplicar dados.
- Retry seguido de envio para DLQ.

Pode usar mocks nos testes unitários. Pelo menos um teste deve passar pelo fluxo real com MySQL e RabbitMQ.

## Entrega

O repositório deve conter:

- Código da API e do worker.
- Migrations ou scripts SQL.
- `docker-compose.yml` capaz de subir a solução completa.
- Testes automatizados.
- `sql/audit_query.sql`.
- README curto com requisitos locais, comandos para subir e testar e até cinco premissas importantes.

Envie somente o link do repositório.

## O que não precisa ser feito

- Frontend.
- Deploy em nuvem.
- Distribuidor de SMS.
- Integração com `webhook.site`.
- Circuit breaker.
- Prints do banco.
- Vídeo Loom.
- Documento de arquitetura.
- Documento conceitual.
- Mais de uma query de auditoria.

Funcionalidades extras não compensam falhas no fluxo principal.

## Critérios de avaliação

| Critério | Peso |
|---|---:|
| Funcionalidade e tratamento de erros | 25% |
| Idempotência e concorrência | 20% |
| RabbitMQ, retry e DLQ | 15% |
| Modelagem e atomicidade no banco | 15% |
| Testes automatizados | 15% |
| Organização, legibilidade e logs | 10% |

## Uso de IA

Você pode usar IA como ferramenta de apoio. Na entrevista técnica, deverá explicar o código entregue, as decisões tomadas e como trataria mudanças no cenário.

## Próxima etapa

Quem avançar fará uma entrevista técnica de 45 a 60 minutos. A conversa será baseada no código entregue e incluirá cenários de falha, escala e evolução da solução.
