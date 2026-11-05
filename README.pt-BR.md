# Raster Priority Mosaic

Versão de desenvolvimento **0.1.0**, software original da [Lofrano Tecnologia](https://lofranotecnologia.com.br), sob licença MIT. [English](README.md).

Aplicação sem interface gráfica para mosaicos pequenos de GeoTIFFs locais, de uma banda uint16. A pessoa chamadora define a grade e as prioridades. As saídas incluem valores, identificação da fonte vencedora, quantidade de contribuições e máscaras explícitas. Um pixel inválido de alta prioridade não apaga um valor válido de prioridade menor. Zero válido continua sendo dado.

Não é um serviço de ingestão genérica, nem uma ferramenta para navegação, levantamento topográfico ou decisões legais sobre limites territoriais. Não há contas, telemetria ou dependência de modelos/APIs.

## Instalação

Ambiente de execução documentado: **Linux e CPython 3.13**, sistema de arquivos com `renameat2(RENAME_NOREPLACE)`, definições EPSG locais e `gdalinfo` do sistema. Os pacotes Python e o GDAL do sistema podem usar bibliotecas nativas diferentes; suas versões são registradas separadamente.

Em Debian Bookworm, com permissão para instalar pacotes:

```sh
apt-get update
apt-get install -y --no-install-recommends gdal-bin python3-venv
python -m venv .venv
. .venv/bin/activate
python -m pip install --only-binary=:all: -r requirements.txt
python -m pip install --no-build-isolation --no-deps -e .
python -m pip check
python tools/check_environment.py
```

Use um interpretador 3.13 para `python`. O Python do sistema Debian não precisa ser 3.13; a imagem `python:3.13-bookworm` fornece o interpretador adequado. A instalação pode acessar repositórios de pacotes. A execução da aplicação, dos testes e da demonstração não baixa dados nem grades. Veja [dependências](docs/dependencies.md): as versões estão fixadas, mas isso não constitui um arquivo de integridade com hashes dos artefatos.

## Testes e demonstração offline

```sh
python -m pytest -q
python -m raster_priority_mosaic demo --assert
python -m raster_priority_mosaic demo --assert --json
```

Execute os testes sequencialmente, sem xdist, com `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1` e `GDAL_NUM_THREADS=1`. O CI limita o contêiner a 1 GiB e duas CPUs. Isso não transforma os analisadores nativos em uma sandbox.

A demonstração cria apenas matrizes sintéticas originais em um diretório temporário próprio. Usa Rasterio/GDAL/PROJ e `gdalinfo` reais, verifica os resultados e remove explicitamente seu espaço temporário. A parte legível por pessoas é:

```text
Raster Priority Mosaic 0.1.0 (development)
data: [[10, 200, 0], [300, 40, 0]]
source_id: [[1, 2, 2], [2, 1, 0]]
coverage: [[1, 2, 2], [2, 1, 0]]
mask: [[255, 255, 255], [255, 255, 0]]
cross_crs_data: [[11, 12], [21, 0]]
assertions: passed
```

Uma linha JSON final contém as matrizes e o estado das verificações. `--json` emite somente esse objeto. Trata-se da saída exemplificada pelo contrato, não de uma alegação de teste executado. O terceiro pixel da primeira linha é um zero válido vencedor. O último pixel é inválido e não possui fonte.

## CLI com saída persistente

```sh
python -m raster_priority_mosaic fixtures synthetic-example
python -m raster_priority_mosaic mosaic synthetic-example/request.json mosaic-example --window-rows 1
```

Resumo esperado: `Published 5 valid pixels to mosaic-example`.

`fixtures` cria dois TIFFs sintéticos e a requisição completa. Os diretórios de destino devem ser novos, com pais já existentes. Acrescente `--json` ao comando `mosaic` para imprimir o relatório inteiro. Saídas concluídas permanecem até remoção explícita pela pessoa chamadora. Nenhum comando sobrescreve um destino existente.

A requisição contém exatamente estes campos. Caminhos relativos são interpretados a partir do diretório do JSON:

```json
{
  "sources": [
    {"path": "a.tif", "source_id": 1, "priority": 10},
    {"path": "b.tif", "source_id": 2, "priority": 20}
  ],
  "targetGrid": {
    "width": 3,
    "height": 2,
    "transform": [1, 0, 0, 0, -1, 2],
    "crs": "EPSG:4326"
  }
}
```

Sucesso retorna código 0. Requisições rejeitadas, erros de processamento e erros de uso retornam 2. Falhas da aplicação imprimem `error:` em stderr, sem traceback. Campos desconhecidos e chaves JSON repetidas são rejeitados. `--version` informa a versão de desenvolvimento. Os nomes dos campos e comandos não são traduzidos.

## API Python

Após criar `synthetic-example`:

```python
from raster_priority_mosaic import Grid, Source, mosaic

sources = [
    Source("synthetic-example/a.tif", source_id=1, priority=10),
    Source("synthetic-example/b.tif", source_id=2, priority=20),
]
grid = Grid(3, 2, (1, 0, 0, 0, -1, 2), "EPSG:4326")
report = mosaic(sources, grid, "api-example", window_rows=1)
print(report["valid_pixels"])  # 5
```

`mosaic(sources, targetGrid, destination, *, window_rows=64)` retorna o mesmo relatório compatível com JSON que grava em `report.json`. Lança `MosaicError` para entrada rejeitada, falha nativa, verificação independente malsucedida ou erro de publicação.

A transformação afim usa **`(a,b,c,d,e,f)`**: `x=a*coluna+b*linha+c`, `y=d*coluna+e*linha+f`, sobre os cantos dos pixels. Não é a ordem de serialização do GDAL. As coordenadas são x/y: longitude/latitude para EPSG:4326. Valores e máscaras são reprojetados separadamente por vizinho mais próximo. `read_masks` considera não zero como válido, ao contrário da polaridade da máscara de `numpy.ma`.

## Arquivos de saída

| Arquivo | Tipo | Significado |
| --- | --- | --- |
| `data.tif` | uint16 | Valor válido de maior prioridade; zero armazenado sem contribuição |
| `source_id.tif` | uint16 | ID da fonte vencedora; zero indica ausência |
| `coverage.tif` | uint8 | Número de contribuições válidas após reprojeção, de 0 a 8 |
| `report.json` | JSON UTF-8 | Geometria, hashes das fontes, histograma e versões reais das bibliotecas/ferramentas |

Os três TIFFs têm máscara interna: 255 quando a cobertura é positiva, 0 caso contrário. Nenhum declara nodata. Todos usam a grade solicitada. A ausência de contribuição não pode ser deduzida apenas do valor numérico de `data.tif`. Um processo separado e limitado de `gdalinfo -json` verifica metadados de cada saída antes da publicação.

## Decisões de projeto

A geometria explícita evita escolher silenciosamente resolução ou um sistema de referência supostamente melhor. Máscaras independentes preservam zeros válidos. Procedência e cobertura tornam as sobreposições auditáveis numericamente. Unidades canônicas de reprojeção de uma linha tornam as matrizes independentes do agrupamento de gravação: `window_rows` altera os buffers, não a malha de amostragem. Um diretório de preparação seguido por renomeação sem substituição publica o pacote inteiro.

Consulte o [contrato preciso](docs/contract.md) e o [projeto](docs/design.md).

## Limitações

- De 1 a 8 fontes; fontes e destino com no máximo 1024 por 1024 e 1.048.576 pixels. Cada arquivo de entrada tem no máximo 64 MiB. A leitura nativa dos metadados ocorre **antes** da verificação das dimensões decodificadas.
- Somente arquivos GTiff locais regulares, autocontidos, de uma banda uint16. Sem URL/VSI/VRT, links simbólicos ou arquivos auxiliares externos de máscara, overview ou PAM.
- Somente EPSG:4326 e EPSG:3857 canônicos, grades orientadas ao norte e extensão inteira dentro de longitude ±180° e latitude ±80°. Sem rotação, cruzamento do antimeridiano ou geometria inferida.
- IDs positivos únicos de 1 a 65535 e prioridades inteiras estritas únicas. A maior prioridade vence; booleanos não são aceitos como inteiros.
- Entradas, diretórios pais e configuração nativa devem permanecer estáveis. Chamadas no mesmo processo são serializadas; apenas um escritor por destino e leitores somente após a publicação. Encerramento abrupto pode deixar preparação ou trava para inspeção manual.
- Cache e memória de warp são ajustes, não garantias de RSS. Analisadores nativos não são isolados pela aplicação. Para entradas hostis, use isolamento e limites do sistema operacional.
- Apenas vizinho mais próximo. Próximo às bordas, valem as convenções do GDAL/PROJ instalado. Testes entre CRSs evitam empates nas bordas. O contrato trata das matrizes, não de TIFFs idênticos byte a byte.
- Publicação atômica não garante durabilidade diante de queda de energia. Não há trava distribuída nem qualificação de sistemas de arquivos remotos.

Contato geral: [site oficial](https://lofranotecnologia.com.br). Relatos de segurança: [canal privado de vulnerabilidades do GitHub](https://github.com/martinlofranodeoliveira/raster-priority-mosaic/security/advisories/new).
