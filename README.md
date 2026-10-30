# achados

Scraper de portais imobiliários que **ordena anúncios por potencial de bom negócio**.
Guarda tudo em SQLite, acompanha o histórico de preços e pontua cada anúncio (0-100).

## Uso

```bash
pip install -e ".[dev]"
cp searches.example.toml searches.toml   # edita as pesquisas
achados scrape                           # recolhe anúncios (corre diariamente)
achados deals --min-score 40 --limit 20  # melhores negócios
achados deals --format csv > achados.csv
pytest
```

## Como é pontuado

| Componente | Pontos | Como |
|---|---|---|
| Desconto €/m² | até 60 | face à **mediana** de comparáveis (concelho+tipologia → concelho → distrito), mín. 5 comparáveis, outliers removidos |
| Descida de preço | até 25 | máx. histórico → preço atual (só conta a partir da 1.ª recolha tua) |
| Palavras-chave | 10 | "urgente", "herdeiros", "oportunidade", "negociável", … |
| Anúncio parado | 5 | ≥ 60 dias na tua base de dados |

Avisos (`!`) para descontos > 60% (provável terreno/ruína/erro de área) e palavras de risco
("ruína", "ocupado", "penhora", …). Um score alto é uma **pista para investigar**, não uma avaliação.

## Fontes

- `imovirtual` — lê `__NEXT_DATA__`. **Escrito sem acesso ao site; valida e ajusta** `sources/imovirtual.py`.
- `jsonld` — genérico, para qualquer página de listagem com JSON-LD schema.org.
- Idealista **não** incluído: bloqueia scraping ativamente; usa a [API oficial](https://developers.idealista.com/access-request).

Para adicionar um site: cria `sources/<nome>.py` com `parse(html, url) -> list[Listing]` e regista-o em `sources/__init__.py`.

## Boas práticas (embutidas)

Respeita `robots.txt`, pausa 4 s (±) entre pedidos, backoff em 429/5xx e **pára em 403** — não
contorna anti-bot. Verifica os termos de utilização de cada portal; uso pessoal e de baixo volume.
