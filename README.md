# VNC-Menu

Interface gráfica para Windows que organiza conexões VNC e algumas tarefas comuns de suporte remoto a partir de uma lista estruturada de hosts.

O projeto foi criado para agilizar o acesso a várias máquinas, reduzir tarefas repetitivas e centralizar operações como conexão VNC, reinício remoto, consulta de sessões, listagem de impressoras e acesso rápido ao compartilhamento administrativo.

<p align="center">
  <img src="assets/VNC-Menu PROMOCIONAL.png" alt="Preview da interface" width="850">
</p>

## Funcionalidades

- Organização de hosts por **Unidade > Setor > Host**.
- Busca de hosts por nome ou IP/hostname dentro da unidade selecionada.
- Suporte a **UltraVNC** e **RealVNC**, com porta configurável por host.
- Credenciais UltraVNC por usuário protegidas com **Windows DPAPI**.
- Preenchimento automático da autenticação UltraVNC, com alternância entre **Login automático** e **Login manual**.
- Listas de hosts compartilhadas ou pessoais.
- Modos de ação para **Conectar** e **Reiniciar** hosts.
- Consulta de sessões remotas com `qwinsta`, executada em paralelo e em segundo plano.
- Listagem de impressoras remotas via **PsExec** + PowerShell.
- Menu de contexto por host com **Copiar IP**, **Abrir c$**, **Abrir Menu Iniciar** e **Impressoras**.
- Configuração de hosts, viewers, PsExec, colunas, tema e posicionamento das janelas.
- Verificação e instalação de atualizações a partir das releases do GitHub.
- Logs de auditoria e erros por usuário, com rotação automática.

## Requisitos

- Windows.
- Python 3.12 ou superior.
- UltraVNC Viewer para conexões UltraVNC.
- RealVNC Viewer para conexões RealVNC.
- PsExec (Sysinternals) para a consulta de impressoras remotas.
- Dependências listadas em `requirements.txt`.

Dependências de execução:

```txt
customtkinter
pywinauto
pywin32
comtypes
```

O `requirements.txt` cobre apenas a execução. Ferramentas de empacotamento não estão nele e não são necessárias para rodar o aplicativo a partir do código-fonte.

## Instalação

Clone o repositório e execute:

```bat
INSTALAR.bat
```

O instalador verifica a pasta do projeto, procura o Python, tenta instalá-lo pelo `winget` caso esteja ausente, recarrega o `PATH` a partir do registro (para concluir a instalação sem precisar rodar o arquivo duas vezes), prepara o `pip`, instala as dependências e valida os imports principais.

Instalação manual:

```bat
py -3 -m pip install -r requirements.txt
```

Executar em modo script:

```bat
py -3 VNC-Menu.pyw
```

## Estrutura do projeto

```text
VNC-Menu.pyw          Ponto de entrada. Ancora data\ e logs\.
VNC-Menu-Updater.pyw  Atualizador executado fora do aplicativo.
vncmenu\              Pacote da aplicação.
├─ config.py          Constantes, caminhos e detecção da raiz da instalação.
├─ dpapi.py           Proteção de credenciais via Windows DPAPI.
├─ applog.py          Log de auditoria e log de erros.
├─ storage.py         Leitura/escrita de JSON, hosts, credenciais, caminhos.
├─ theme.py           Paleta e fontes.
├─ helpers.py         Utilitários de janela, arquivos e viewers.
├─ updates.py         Consulta e download de releases.
├─ remote.py          VNC, reinício remoto, qwinsta, PsExec, impressoras.
└─ ui\
   ├─ dialogs.py      Diálogos modais compartilhados.
   ├─ windows.py      Janelas de configuração, progresso e atualização.
   └─ app.py          Janela principal.
data\                 Dados compartilhados da instalação.
logs\                 Logs por usuário do Windows.
tests\                Suíte de testes (não é necessária para usar o app).
```

`VNC-Menu.pyw` precisa permanecer na raiz da instalação e manter esse nome: `data\` e `logs\` são resolvidos a partir dele, e o atualizador reinicia o aplicativo por esse nome.

## Uso

### Organização dos hosts

Os hosts são organizados em:

```text
Unidade
└─ Setor
   └─ Host
```

Cada host possui:

- `name`: nome exibido na interface;
- `host`: hostname ou endereço IP;
- `viewer`: `ultravnc` ou `realvnc`;
- `port`: opcional, porta VNC do host.

### Ações principais

Na tela principal:

- **Conectar**: modo de ação. Um clique no host abre o viewer configurado.
- **Reiniciar**: modo de ação. Um clique no host pede confirmação e envia o reinício.
- **Usuários**: consulta as sessões remotas dos hosts do setor com `qwinsta`.
- **Impressoras**: lista as impressoras instaladas no host.

**Conectar** e **Reiniciar** também aceitam duplo clique no próprio botão para agir sobre um host digitado na hora.

As consultas de usuários e de impressoras são executadas em segundo plano, com janela de progresso, para manter a interface responsiva. A consulta `qwinsta` é feita em paralelo.

### Login automático e login manual

O botão ao lado de **Host manual** alterna entre:

- **Login automático**: para hosts cadastrados, o aplicativo preenche a autenticação UltraVNC com a credencial salva;
- **Login manual**: a janela de autenticação do UltraVNC é deixada para o usuário.

Conexões manuais nunca usam o preenchimento automático.

### Host manual

O botão **Host manual** segue o modo atualmente selecionado:

- em **Conectar**, solicita hostname/IP e viewer;
- em **Reiniciar**, solicita hostname/IP e confirmação.

Em **Conectar**, o campo aceita porta explícita no formato `HOST::5901`.

### Busca

A barra acima dos botões procura hosts pelo **nome** ou pelo **IP/hostname**, em todos os setores da **unidade selecionada**. Cada resultado mostra o nome, o endereço e o setor a que pertence.

A busca ignora maiúsculas e acentos, então `recepcao` encontra `Recepção`.

Enquanto há uma busca ativa:

- os setores deixam de comandar a lista e aparecem esmaecidos;
- a área acima da lista mostra `Buscando em: <unidade>`;
- clicar em um setor, trocar de unidade, pressionar `Esc` ou usar o botão `✕` volta à navegação normal.

O modo selecionado continua valendo: clicar em um resultado conecta ou reinicia, conforme **Conectar** ou **Reiniciar** estiver ativo. O clique com o botão direito abre o mesmo menu de contexto da lista normal.

A busca não é salva. Ao reabrir o aplicativo, a lista volta ao setor selecionado.

### Menu de contexto

Clique com o botão direito sobre um host para acessar:

- **Host/IP**: mostra o valor configurado em `host` (apenas informativo);
- **Copiar IP**: copia esse valor;
- **Abrir c$**: tenta abrir `\\HOST\c$`;
- **Abrir Menu Iniciar**: abre a pasta de inicialização de todos os usuários da máquina remota:

```text
\\HOST\c$\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup
```

- **Impressoras**: lista as impressoras instaladas no host.

O acesso a `C$` depende das permissões do usuário, disponibilidade do SMB, firewall e políticas da rede.

### Edição de hosts

A tela:

```text
Configurações > Hosts e Setores
```

permite adicionar, editar, remover, reordenar e ordenar hosts, além de gerenciar unidades e setores.

Na lista de hosts:

- clique simples seleciona;
- duplo clique abre diretamente a edição do host.

## Formato do hosts.json

Exemplo:

```json
{
  "units": [
    {
      "name": "Main Office",
      "sectors": [
        {
          "name": "Support",
          "hosts": [
            {
              "name": "Workstation 01",
              "host": "192.168.1.10",
              "viewer": "ultravnc"
            },
            {
              "name": "Workstation 02",
              "host": "192.168.1.11",
              "viewer": "ultravnc",
              "port": 5901
            },
            {
              "name": "Server 01",
              "host": "192.168.1.20",
              "viewer": "realvnc"
            }
          ]
        }
      ]
    }
  ]
}
```

Valores suportados para `viewer`:

```txt
ultravnc
realvnc
```

Se `viewer` for omitido ou inválido, o aplicativo usa `ultravnc` como padrão.

`port` é opcional e aceita valores de 1 a 65535. Quando ausente, inválido ou igual a `5900`, o campo é omitido ao salvar e o aplicativo usa a porta padrão. O campo `host` também aceita a porta embutida (`HOST::5901`); nesse caso ela é extraída para `port` na próxima gravação.

## Modos da lista de hosts

Selecionáveis em `Configurações > Selecionar Lista`.

### Padrão

Usa o `data\hosts.json` compartilhado da instalação.

Indicado quando vários usuários devem utilizar a mesma lista.

### Personalizada

Cria uma cópia pessoal em:

```text
Documents\VNC-Menu\hosts.json
```

Indicado quando o usuário precisa editar sua própria lista sem afetar outros usuários.

### Vazia

Cria uma lista pessoal sem nenhum host, para iniciar uma configuração do zero.

## UltraVNC

Caminho padrão:

```text
C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe
```

O caminho pode ser alterado em:

```text
Configurações > Viewers VNC
```

O aplicativo usa um `template.vnc` compartilhado. Durante a conexão:

1. o template é copiado para um arquivo temporário;
2. o UltraVNC é iniciado com `-config`;
3. o destino é passado separadamente como:

```text
HOST::5900
```

Fluxo equivalente:

```text
vncviewer.exe -config <arquivo-temporario.vnc> HOST::5900
```

Se o host tiver `port` configurada, ela substitui `5900`.

### Onde fica o template.vnc

O arquivo esperado é `data\template.vnc`. Ele **não** é versionado: um perfil exportado do UltraVNC Viewer pode carregar a senha de conexão salva (`passwd` / `passwd2`).

O repositório inclui `data\template.vnc.example`, que não contém senha. Na primeira execução, se `template.vnc` não existir, o VNC-Menu copia o exemplo para o lugar. Um `template.vnc` já existente nunca é sobrescrito.

**O template exige o SecureVNC.** Ele vem com `UseDSMPlugin=1` e `DSMPlugin=SecureVNCPlugin64.dsm`, então as conexões só funcionam com esse plugin instalado no viewer e configurado no servidor remoto. Se a sua instalação não usa SecureVNC, defina `UseDSMPlugin=0` e `DSMPlugin=` em `data\template.vnc`. Veja `data\LEIA-ME-template-vnc.txt`.

Para a senha, prefira `Configurações > Credenciais UltraVNC`, que a guarda protegida por DPAPI no perfil do usuário em vez de em texto plano no disco.

## RealVNC

Caminho padrão:

```text
C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe
```

O caminho também pode ser alterado em:

```text
Configurações > Viewers VNC
```

Os perfis RealVNC ficam em `data\realvnc` e seguem o formato:

```text
<Setor>_<Nome do Host>.vnc
```

Exemplo:

```text
Support_Workstation 01.vnc
```

Se o perfil não existir ou estiver vazio, o aplicativo informa o arquivo esperado.

## PsExec e impressoras remotas

A listagem de impressoras executa um coletor PowerShell na máquina remota através do PsExec e devolve, para cada fila instalada:

- nome da impressora;
- driver;
- porta e endereço (IP ou `USB`);
- se é compartilhada e o servidor de origem, quando aplicável.

O caminho do PsExec é definido em:

```text
Configurações > PsExec
```

Vale para todos os usuários do computador (fica em `data\paths.json`). Se o campo ficar vazio, o aplicativo procura o PsExec no `PATH`.

Falhas comuns são traduzidas para uma mensagem legível, como host inacessível, nome não resolvido, credenciais recusadas e tempo esgotado, em vez do código bruto do PsExec.

## Credenciais e configurações por usuário

As credenciais são configuradas em:

```text
Configurações > Credenciais UltraVNC
```

Arquivos individuais ficam em:

```text
C:\Users\<usuario>\Documents\VNC-Menu\
├─ creds.json
├─ settings.json
└─ hosts.json
```

- `creds.json`: credenciais UltraVNC protegidas com Windows DPAPI.
- `settings.json`: preferências da interface, seleção atual e geometria das janelas.
- `hosts.json`: lista pessoal quando o modo **Personalizada** ou **Vazia** é usado.

Caso o Windows negue acesso de escrita a `Documents\VNC-Menu\settings.json`, o aplicativo utiliza:

```text
%APPDATA%\VNC-Menu\settings.json
```

como fallback para evitar falhas de inicialização.

Os caminhos dos viewers e do PsExec são compartilhados pela instalação e ficam em `data\paths.json`.

## Dados compartilhados da instalação

```text
.\data\
├─ hosts.json             Lista compartilhada.
├─ paths.json             Caminhos dos viewers e do PsExec.
├─ template.vnc           Modelo UltraVNC em uso (não versionado).
├─ template.vnc.example   Modelo de exemplo, sem senha (versionado).
└─ realvnc\               Perfis RealVNC.
```

Todas as gravações de JSON são atômicas: o conteúdo é escrito em um arquivo temporário na mesma pasta, sincronizado em disco e só então substitui o destino. Uma queda de energia no meio da gravação não deixa o arquivo pela metade.

## Atualizações

O aplicativo consulta a release mais recente em:

```text
https://github.com/gabrielmariense/VNC-Menu/releases
```

A verificação automática ao iniciar pode ser desligada em `Configurações > Atualizações ao iniciar`. A verificação manual fica em `Configurações > Sobre > Buscar atualização`.

Quando há uma versão nova, o download é feito com barra de progresso e a instalação é entregue ao `VNC-Menu-Updater.pyw`, que roda fora do aplicativo, substitui os arquivos e reinicia o VNC-Menu. Os dados do usuário e o conteúdo de `data\` são preservados.

## Logs

Os logs ficam na pasta `logs` do aplicativo:

```text
.\logs\<usuario-windows>.log
.\logs\<usuario-windows>_error.log
```

São registrados eventos como:

- início do aplicativo;
- conexões VNC;
- reinícios remotos;
- consultas `qwinsta`;
- consultas de impressoras;
- alterações na lista de hosts;
- mudanças de configuração;
- cópia de host/IP;
- abertura do compartilhamento `C$` e do Menu Iniciar remoto;
- atualizações;
- erros internos.

Os dois arquivos têm limite de tamanho e mantêm uma geração anterior como `<nome>.log.1`.

## Testes

A suíte usa apenas a biblioteca padrão e roda com a interface gráfica simulada, em uma pasta temporária própria. Nada em `Documents\VNC-Menu` ou em `data\` é alterado.

```bat
py -3 -m unittest discover -s tests -v
```

Os testes não são necessários para usar o aplicativo.

## Gerando o executável

O modelo de distribuição padrão é o código-fonte com o atualizador. Empacotar é opcional.

Instale as dependências de execução e o empacotador:

```bat
py -3 -m pip install -r requirements.txt
py -3 -m pip install pyinstaller
```

Exemplo com PyInstaller:

```bat
py -3 -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --clean ^
  --name "VNC-Menu" ^
  --contents-directory _internal ^
  "VNC-Menu.pyw"
```

O conteúdo de `data\` não deve ser embutido no executável: ele é gravável e pertence à instalação. Copie a pasta `data\` para o lado do executável gerado.

## Observações

- Atualmente, somente UltraVNC e RealVNC são suportados.
- Os viewers VNC e o PsExec não são incluídos no projeto.
- Credenciais protegidas por DPAPI não são compartilháveis diretamente entre usuários Windows.
- Reinício remoto, `qwinsta`, PsExec e acesso a `C$` dependem das permissões e políticas do ambiente.
- Alterações na lista compartilhada podem afetar todos os usuários da mesma instalação.
- Arquivos como `creds.json`, `settings.json`, `data\template.vnc` e perfis sensíveis não devem ser versionados.

## Licença

Este projeto é distribuído sob a licença MIT. Consulte o arquivo [LICENSE](https://github.com/gabrielmariense/VNC-Menu/blob/main/LICENSE).
