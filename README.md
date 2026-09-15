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
- Reexecução do script de mapeamento de impressoras **na sessão do usuário logado**, com instalação prévia dos drivers na máquina.
- Menu de contexto por host com **Copiar IP**, **Abrir c$**, **Abrir Menu Iniciar**, **Impressoras** e **Sessões**; a janela de host manual tem as mesmas ações, menos **Copiar IP** (ali o endereço acabou de ser digitado).
- Configuração de hosts, viewers, PsExec, colunas, tema e posicionamento das janelas.
- Verificação e instalação de atualizações a partir das releases do GitHub.
- Logs de auditoria e erros por usuário, com rotação automática.

## Credenciais e digitação automática

Com o login automático ligado, o app espera o diálogo de autenticação do
UltraVNC e preenche a credencial salva. Duas regras sustentam isso:

- A credencial é escrita **somente** com `set_text()`, que grava no controle
  pelo handle dele. Diferente de `send_keys()`, não depende de qual janela está
  em primeiro plano, então a senha não tem como cair na barra de busca, num
  chat ou em qualquer campo que você clique enquanto o viewer abre. O módulo
  nem importa `send_keys`, de propósito.
- Fechar o viewer (ou a janela de credenciais) **cancela** o preenchimento na
  hora. O processo do viewer é o sinal: quando ele sai, a thread para, em vez
  de continuar viva até o tempo limite e digitar no que aparecer.

Se os campos do diálogo não forem identificados, o app **desiste** e você
digita. Não existe caminho "às cegas" — ele foi removido justamente por ser o
único que digitava sem um controle amarrado.

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
- **Impressoras**: abre a janela de impressoras do host.

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

- **Impressoras**: abre a janela de impressoras já com o host preenchido. Nada
  é consultado sozinho: um menu aberto por engano não dispara PsExec contra a
  máquina.

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

## Janela de Impressoras

Uma janela só para o atendimento inteiro de impressora: consultar o que está
mapeado, reexecutar o script e consultar de novo para conferir. A saída é
compartilhada pelas duas ações, para dar para comparar antes e depois sem
trocar de janela.

Abrindo pela lista de hosts ou pelo menu de contexto, o campo já vem
preenchido; pelo botão da barra, vem vazio. Em nenhum dos casos algo roda
sozinho — consultar e reexecutar têm custos diferentes na máquina do usuário,
então a escolha é sempre explícita.

A parte de script tem o nome do arquivo (varia por máquina), um botão que abre
a pasta pelo `c$` para conferir o nome, e a caixa de instalação de drivers:

```text
C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup
```

### Por que o script não roda como SYSTEM

O script usa `AddWindowsPrinterConnection` e `SetDefaultPrinter`, que gravam no
`HKCU` de **quem chama**. Rodando como SYSTEM — ou com a conta do analista — as
impressoras seriam mapeadas no perfil errado e o usuário na máquina não veria
diferença nenhuma.

Por isso a execução é assim:

1. PsExec roda um PowerShell como SYSTEM na máquina.
2. Esse PowerShell descobre o usuário logado (`Win32_ComputerSystem.UserName`,
   com o dono do `explorer.exe` como reserva).
3. Cria uma tarefa agendada temporária com `LogonType Interactive`, que usa o
   **token da sessão já aberta** e por isso não pede a senha do usuário.
4. Dispara a tarefa, espera terminar e remove a tarefa.

O `.vbs` roda pelo **wscript** em modo batch (`//nologo //B`), que não tem
console: nada aparece na tela do usuário e não há janela para ele fechar no
meio — fechar o console do `cscript` matava o script, possivelmente depois de
apagar as impressoras e antes de remapear. Arquivos `.cmd` e `.bat` não têm
equivalente: o `cmd.exe` abre prompt, e a confirmação avisa isso antes.

A tarefa é criada com `-AllowStartIfOnBatteries` (o padrão do Windows é não
iniciar tarefa com a máquina na bateria, o que fazia um notebook reportar
"nunca entrou em execução") e com limite de execução próprio, para o Windows
matar um script travado depois que o app já removeu a tarefa e foi embora.

Sem ninguém logado, nada é executado: sem token de usuário, rodar como SYSTEM
deixaria a máquina pior do que estava.

### Instalação dos drivers

`AddWindowsPrinterConnection` faz duas coisas com exigências diferentes:

| Etapa | Onde grava | Exige |
|---|---|---|
| Instalar o driver vindo do servidor | driver store da **máquina** | privilégio administrativo |
| Criar a conexão da impressora | `HKCU` do **usuário** | o token dele |

Desde o patch do PrintNightmare (KB5005652), `RestrictDriverInstallationToAdministrators`
vem ligado por padrão: usuário comum não instala driver de impressora, nem
manualmente. É isso que faz uma máquina ficar sem puxar a fila do servidor por
mais que o script rode.

Por isso, **antes** de executar o script, o app lê os caminhos
`\\servidor\fila` escritos no próprio `.vbs` e roda `Add-Printer -ConnectionName`
para cada um, como SYSTEM. O driver vai para o driver store da máquina; depois
disso, o mapeamento no contexto do usuário não precisa mais de administrador.

Não é opcional e não tem caixa de seleção: é barato (fila já instalada conta
como sucesso), não pede credencial nenhuma, e deixar a cargo do operador só
funcionaria se ele soubesse de antemão quais máquinas precisam — que é
justamente o que ele não sabe antes de tentar.

Notas:

- Roda como **SYSTEM**, que se apresenta ao servidor de impressão como a conta
  de máquina (`DOMÍNIO\NOME-DO-PC$`). É o mesmo caminho que a consulta de
  impressoras já usa para ler as filas do servidor.
- Rodar com credencial nominal (`psexec -u/-p`) foi tentado e **não serve**: o
  PsExec faz logon interativo no computador remoto, e a conta administrativa
  não tem esse direito nas estações — logon 1385, com a senha correta.
- `Add-Printer` lança erro de verdade, então a janela mostra **qual fila**
  falhou e **por quê** — que é o diagnóstico que o `.vbs` não dá.
- A conexão criada fica no perfil do SYSTEM. É de propósito: o que interessa é
  o driver, e removê-la depois só acrescentaria um jeito de falhar depois do
  objetivo já alcançado.
- Se a instalação não chega a rodar, o script **não** é executado: apagar as
  impressoras do usuário sem garantia de remapear deixaria a máquina pior.

### Limites

- O resultado da execução **não prova** que as impressoras voltaram. O script
  mantém `ON ERROR RESUME NEXT` ligado do início ao fim, então sai com código 0
  mesmo falhando. A confirmação é consultar de novo, no mesmo lugar.
- Enquanto o script roda, as impressoras do usuário ficam indisponíveis: ele
  apaga todas as filas e conexões de rede antes de remapear.
- A instalação de drivers só encontra as filas escritas como literal entre
  aspas no `.vbs`. Um script que monte o caminho por variável ou laço é
  reportado como "nenhum caminho encontrado", não silenciosamente ignorado.
- `Register-ScheduledTask` com logon interativo depende da política de tarefas
  agendadas do domínio. Quando ela recusa, a janela mostra a mensagem do
  Windows em vez de tentar outro caminho por conta própria.
- O campo do script aceita apenas um **nome de arquivo** `.vbs`, `.cmd` ou
  `.bat`, sem caminho, para o campo não virar execução remota de qualquer
  arquivo.

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
