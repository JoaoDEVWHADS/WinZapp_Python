# WinZapp (Fork)

> **Este repositório é um [Fork do Repositório Original de Gabriel Haberkamp](https://github.com/gabrielhhaber/WinZapp_Python).**  
> Todos os créditos pelo desenvolvimento inicial e arquitetura do projeto pertencem ao autor original. Este fork foca em estabilização, automação de compilação, correções de bugs de acessibilidade e reestruturação do sistema de atualização.

---

WinZapp é um **cliente desktop de WhatsApp, gratuito, auto-hospedado e de código aberto para Windows**, desenvolvido principalmente com foco em **acessibilidade para usuários cegos ou com baixa visão**.
Ele integra-se perfeitamente com leitores de tela (como NVDA, JAWS, Narrator e outros) através do ecossistema [accessible-output2](https://github.com/accessibleapps/accessible_output2) e oferece uma interface totalmente navegável pelo teclado usando wxPython.

O aplicativo roda de forma híbrida:
1. **Cliente Gráfico:** Escrito em Python 3.13 + wxPython (responsável pela GUI, alertas sonoros e leitura de tela).
2. **Evolution API:** Rodando localmente em Node.js (com banco de dados PostgreSQL embutido) atuando como gateway de comunicação.

---

## 🛠️ O que foi melhorado neste Fork?

Desde o fork original, implementei uma reestruturação profunda nas seguintes áreas:

### 1. Automação de CI/CD & Releases (GitHub Actions)
* **Pipeline de Release Automática:** Criei o workflow [release.yml](file:///.github/workflows/release.yml) rodando em ambiente Windows Server. A cada `git push` na branch `main`:
  * A esteira gera automaticamente uma versão baseada em data/hora UTC (`AAAA.MM.DD.HHMM`, ex: `2026.06.17.2208`).
  * Atualiza o arquivo [version.py](file:///client/version.py) e commita no GitHub ignorando loops recursivos (`[skip ci]`).
  * Executa todo o processo de build (configura MSYS2 para GCC/windres, baixa Node.js portátil, compila Evolution API e executa PyInstaller).
  * Cria uma GitHub Release e publica os binários executáveis prontos para download.
* **Caches Avançados:** Implementei caching estruturado para o compilador MSYS2, pacotes `pip` (Python), binários do Node.js e `node_modules` da Evolution API, reduzindo drasticamente o tempo de build em nuvem.

### 2. Reformulação do Atualizador Automático (Zero Conflitos)
* **Integração Direta com o GitHub:** Removi a dependência de arquivos JSON e TXT estáticos no repositório. O atualizador agora consulta diretamente a API de Releases do GitHub, extraindo a última versão e changelog nativos da plataforma.
* **Resolução de Bloqueio de Arquivos (File Lock):** O atualizador antigo falhava silenciosamente porque o banco de dados PostgreSQL e a Evolution API continuavam rodando e travando os arquivos da pasta de instalação. Corrigi isso no script de atualização inserindo uma busca dinâmica de portas:
  * O atualizador identifica e encerra os processos vinculados às portas **3417** (Evolution API) e **5433** (PostgreSQL) usando a tabela de conexões ativas (`netstat` + `taskkill`). Isso garante que 100% das travas sejam liberadas e a atualização ocorra sem erros de acesso negado.

### 3. Migração do Compilador para PyInstaller
* Substituí a compilação antiga (feita via Nuitka) por uma estrutura robusta baseada em **PyInstaller** (`build.py`).
* Corrigi o empacotamento de DLLs dinâmicas críticas de áudio (BASS DLLs) e leitores de tela (`accessible-output2`) que eram descartadas e causavam crash do executável.
* O build agora empacota tudo em uma pasta limpa (`_internal/` e diretórios irmãos) e gera o instalador nativo do Windows (`WinZappInstaller.exe`) usando código stub compilado via GCC.

### 4. Correções de Bugs Críticos no App
* **Fim das falhas 401 (Unauthorized):** Ajustei o script de boot da API local ([start.js](file:///client/api/start.js)) e do cliente Python para sincronizarem e preservarem a variável de ambiente `AUTHENTICATION_API_KEY` (usando chaves de licença registradas sem sobrescrever o token local).
* **Compatibilidade com Linked Devices (LID):** Corrigi o problema de contatos e conversas que apareciam com nome em branco por conta de JIDs vinculados a dispositivos secundários (`@lid`).
* **Estabilização de Diálogos:** Corrigi um erro de `AttributeError` no cliente ao tentar se reconectar ou ao destruir elementos gráficos em momentos de desconexão repentina.
* **Filtragem de Grupo:** Impedido que JIDs de grupos de WhatsApp fossem erroneamente formatados como números de telefone normais.

---

## 💻 Ambiente de Desenvolvimento

### Pré-requisitos
* **Python 3.13** instalado no sistema.
* **Git** para controle de versão.
* Para builds locais do instalador: **GCC** e **windres** (disponíveis via MSYS2).

### Passos para rodar localmente:
```powershell
# 1. Clone o repositório
git clone git@github.com:JoaoDEVWHADS/WinZapp_Python.git
cd WinZapp_Python

# 2. Crie e ative o ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Inicie o cliente em modo de desenvolvimento
cd client
python main.py
```

---

## 📦 Compilação Local (Build)

Para compilar e gerar o instalador `WinZappInstaller.exe` e a versão portátil `WinZapp.zip` localmente em sua máquina Windows:

```powershell
# Com a venv ativa e ferramentas C (GCC/windres no PATH):
python build.py
```

Os arquivos finais compilados serão gerados dentro do diretório `dist/` na raiz do projeto.

---

## 📄 Licença e Aviso Legal

O WinZapp é um projeto sob licença GPL. Ele depende de engenharia reversa do protocolo do WhatsApp Web. O uso do software é de sua total responsabilidade. Este repositório não é afiliado, mantido ou patrocinado pela Meta Platforms, Inc.
