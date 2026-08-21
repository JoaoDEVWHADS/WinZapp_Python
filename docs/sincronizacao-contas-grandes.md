# Sincronização de contas grandes sem reinícios em loop

## Resumo

Esta correção separa três trabalhos que antes acabavam acoplados:

1. obter uma lista confiável de conversas;
2. caminhar o histórico de cada conversa até o início disponibilizado pelo WhatsApp;
3. baixar as mídias elegíveis que ainda não estejam no cache local.

Uma falha transitória na lista de conversas não reinicia mais as outras duas etapas. Ao mesmo tempo, uma lista confiável não significa que o histórico foi considerado completo: cada conversa continua sendo paginada e somente avanço real no banco de dados é contabilizado.

## Sintoma observado

Em uma conta com mais de 600 conversas, o log mostrou esta sequência:

- a primeira chamada de `list-chats` retornou 680 conversas;
- o cache local continha 681;
- o Store interno do WhatsApp Web informava 682;
- chamadas posteriores de `list-chats` retornaram zero;
- a conexão continuou no estado `CONNECTED`;
- a rodada era marcada como incompleta e o verificador de saúde iniciava outra;
- depois de duas rodadas, a sessão do WPPConnect era recriada;
- cada rodada examinava novamente aproximadamente 8.700 mensagens de mídia, embora baixasse zero arquivos;
- o histórico profundo dizia armazenar 5.265 mensagens mais antigas por passagem, mas 46 conversas continuavam sempre pendentes.

O problema, portanto, não era uma simples queda de internet nem o desaparecimento das conversas.

## Causas

### 1. Uma resposta válida era invalidada por uma resposta vazia posterior

`list-chats` usa a lista em memória do WA-JS. Essa rota pode responder corretamente e, instantes depois, retornar uma lista vazia mesmo com os dados ainda presentes no Store/IndexedDB do WhatsApp Web.

O sincronizador conservava os chats mesclados em memória, mas marcava a lista como não estabilizada. Isso deixava `_sync_completed` falso e autorizava a repetição global da sincronização.

### 2. Uma rodada incompleta repetia a varredura de mídia

A fase automática de mídia era executada mesmo quando a lista de chats já tinha sido considerada incompleta. Como a rodada seria repetida, milhares de registros já conhecidos eram examinados novamente. O código evitava gravar novamente os arquivos existentes, mas ainda havia custo de CPU, tarefas e mensagens de estado para o usuário.

### 3. Páginas repetidas eram contabilizadas como histórico novo

Ao não encontrar no Store do navegador a âncora solicitada, a rota de mensagens antigas podia devolver a mesma página de 200 mensagens. O SQLite eliminava os IDs repetidos, porém `deep_backfill_chat()` somava `len(page)` e tratava a resposta como progresso.

Esse falso progresso renovava o prazo do backfill e mantinha o ciclo ativo.

## Solução implementada

### Snapshot confiável da lista de conversas

Durante cada rodada mantemos o maior snapshot não vazio realmente recebido naquela própria rodada. Se uma resposta posterior diminuir ou zerar, comparamos esse snapshot com `storeCounts.chat`, obtido por uma rota independente.

O snapshot é aceito quando a diferença está dentro de:

- uma conversa, para contas pequenas, ou 1% do total para contas maiores; e
- o snapshot ainda representa pelo menos 95% do total informado pelo Store.

A segunda condição impede que a tolerância absoluta esconda uma perda proporcionalmente grande numa conta pequena, como `1/2` ou `9/10`.

Assim:

- `680/682` é considerado o mesmo conjunto prático e preservado;
- `935/937` também é considerado confiável;
- `36/682` ou `36/937` continua sendo rejeitado como conta amputada.

Somente snapshots recebidos na rodada atual podem concluir essa rodada. O maior número visto numa rodada anterior continua servindo como evidência de Store quebrado, mas não pode substituir um payload que não foi recebido novamente.

### Histórico continua sendo completo por conversa

Aceitar a lista de chats resolve apenas a descoberta das conversas. Não marca o histórico individual como concluído.

Para cada página antiga, o backfill agora registra:

- a âncora mais antiga antes da consulta;
- a quantidade de linhas no banco antes da consulta;
- a nova âncora mais antiga depois da gravação;
- a quantidade de linhas depois da gravação.

Só existe progresso quando:

1. a âncora no banco realmente se move para trás; e
2. a contagem do SQLite aumenta com IDs inéditos.

O número anunciado e usado para renovar o prazo é a diferença real de linhas, não o tamanho da resposta HTTP.

Quando a página não avança:

- ela não é contabilizada;
- a âncora é colocada em espera;
- o WinZapp solicita histórico anterior ao telefone uma vez;
- novas consultas dessa mesma âncora são pausadas;
- se uma sincronização de histórico inserir mensagens mais antigas e mudar a âncora do banco, o chat volta automaticamente à fila ativa.

Os chats pausados ficam atrás dos chats que ainda conseguem avançar. Dessa forma, uma conversa problemática não impede as demais de serem percorridas.

### Mídias somente após uma rodada válida

A fase automática de mídia não roda quando a lista de chats ficou incompleta. O verificador de saúde ainda poderá repetir a etapa necessária, mas não examinará milhares de mídias em cada tentativa inválida.

Após uma rodada confiável, o comportamento de mídia permanece o mesmo: limites de idade e tamanho, cache local, IDs expirados e configuração do usuário continuam sendo respeitados.

## Garantia de completude e limite externo

O WinZapp continua tentando armazenar todas as mensagens que o WhatsApp disponibilizar ao dispositivo vinculado. Uma conversa somente sai da caminhada normal quando a API informa que não existe uma página anterior ou quando aguarda uma resposta de histórico do telefone.

Existe um limite que o cliente não consegue ultrapassar: mensagens que o WhatsApp não entrega ao WhatsApp Web não podem ser recuperadas pelo WinZapp. Nessa situação, a correção mantém o estado como pendente/aguardando, em vez de inventar progresso ou reiniciar toda a conta.

## Impacto esperado

- contas grandes deixam de reiniciar a sincronização por causa de uma sequência como `680 → 0`;
- uma lista pequena e realmente parcial não é aceita;
- mensagens já armazenadas permanecem preservadas;
- o histórico profundo avança de forma durável pelo SQLite;
- páginas duplicadas não renovam o backfill;
- conversas com problema não bloqueiam as demais;
- a varredura automática de mídia não se repete em rodadas sabidamente incompletas;
- a interface continua utilizável enquanto o histórico restante é buscado em segundo plano.

## Testes de regressão

Foram adicionados ou ampliados testes para verificar:

- snapshot `680 → 0` confirmado por Store `682`;
- rejeição de snapshot `36/682`;
- manutenção das proteções para Store frio e conta vazia;
- ausência da fase de mídia numa rodada incompleta;
- interrupção imediata quando a API repete a mesma página;
- uma única solicitação de histórico mais antigo para uma âncora parada;
- retomada baseada na âncora persistida no banco;
- contabilização apenas de IDs que realmente aumentaram a tabela de mensagens;
- manutenção do limite de páginas por conversa e da fila entre conversas.

Comando da bateria focada:

```powershell
venv\Scripts\python.exe -m pytest tests/test_run_sync_broken_store.py tests/test_chat_list_settled.py tests/test_deep_history_backfill.py tests/test_media_sync_count.py -q
```

Resultado durante o desenvolvimento: `135 passed` nessa bateria focada e `185 passed` na validação ampliada da branch.

## Arquivos principais

- `client/main.py`: decisão de snapshot, controle da fase de mídia e avanço do histórico profundo;
- `tests/test_run_sync_broken_store.py`: cenários reais da lista de chats e fase de mídia;
- `tests/test_deep_history_backfill.py`: avanço, repetição e contabilização do histórico;
- `docs/sincronizacao-contas-grandes.md`: este registro técnico.
