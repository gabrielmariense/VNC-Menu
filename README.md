# VNC-Menu

Interface gráfica para Windows que organiza conexões VNC e algumas tarefas comuns de suporte remoto a partir de uma lista estruturada de hosts.

O projeto foi criado para agilizar o acesso a várias máquinas, reduzir tarefas repetitivas e centralizar operações como conexão VNC, reinício remoto, consulta de sessões e acesso rápido ao compartilhamento administrativo.

<p align="center">
  <img src="assets/VNC-Menu PROMOCIONAL.png" alt="Preview da interface" width="850">
</p>

## Funcionalidades

- Organização de hosts por **Unidade > Setor > Host**.
- Suporte a **UltraVNC** e **RealVNC**.
- Credenciais UltraVNC por usuário protegidas com **Windows DPAPI**.
- Listas de hosts compartilhadas ou pessoais.
- Modos de ação para **Conectar** e **Reiniciar** hosts.
- Consulta de sessões remotas com `qwinsta`, executada em segundo plano.
- Menu de contexto por host com **Copiar IP** e **Abrir pasta** (`\\HOST\c$`).
- Configuração de hosts, viewers, colunas, tema e posicionamento das janelas.
- Logs de auditoria e erros por usuário.
- Compatibilidade com empacotamento via **PyInstaller**.

## Requisitos

- Windows.
- Python 3.12 ou superior.
- UltraVNC Viewer para conexões UltraVNC.
- RealVNC Viewer para conexões RealVNC.
- Dependências listadas em `requirements.txt`.

Dependências atuais:

```txt
pywinauto==0.6.9
pyinstaller>=6.0,<7.0
pywin32>=306
comtypes>=1.4.0
customtkinter>=5.2.2
```

## Instalação

Clone o repositório e execute:

```bat
INSTALAR.bat
```

O instalador verifica a disponibilidade do Python, tenta instalá-lo pelo `winget` caso esteja ausente, atualiza o `pip`, instala as dependências e valida os imports principais.

Instalação manual:

```bat
py -3 -m pip install -r requirements.txt
```

Executar em modo script:

```bat
py -3 VNC-Menu.pyw
```

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
- `viewer`: `ultravnc` ou `realvnc`.

### Ações principais

Na tela principal, selecione o modo desejado:

- **Conectar**: abre o viewer configurado para o host.
- **Reiniciar**: solicita confirmação e envia um reinício remoto.
- **Usuários**: consulta sessões remotas com `qwinsta`.

A consulta de usuários é executada em segundo plano para manter a interface responsiva e exibe uma janela de progresso durante a operação.

### Host manual

O botão **Host manual** segue o modo atualmente selecionado:

- em **Conectar**, solicita hostname/IP e viewer;
- em **Reiniciar**, solicita hostname/IP e confirmação.

Conexões manuais UltraVNC não utilizam o preenchimento automático da senha salva.

### Menu de contexto

Clique com o botão direito sobre um host para acessar:

- **Copiar IP**: copia o valor configurado em `host`;
- **Abrir pasta**: tenta abrir o compartilhamento administrativo:

```text
\\HOST\c$
```

O acesso a `C$` depende das permissões do usuário, disponibilidade do SMB, firewall e políticas da rede.

### Edição de hosts

A tela:

```text
Configurações > Hosts VNC
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

## Modos da lista de hosts

### Padrão

Usa o `hosts.json` compartilhado da instalação.

Indicado quando vários usuários devem utilizar a mesma lista.

### Personalizada

Cria uma cópia pessoal em:

```text
Documents\VNC-Menu\hosts.json
```

Indicado quando o usuário precisa editar sua própria lista sem afetar outros usuários.

### Vazia

Cria uma lista pessoal limpa para iniciar uma configuração do zero.

## UltraVNC

Caminho padrão:

```text
C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe
```

O caminho pode ser alterado em:

```text
Configurações > Caminhos dos Viewers
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

Para hosts cadastrados, o aplicativo pode preencher automaticamente as credenciais UltraVNC salvas. Esse preenchimento é desabilitado em conexões manuais.

## RealVNC

Caminho padrão:

```text
C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe
```

O caminho também pode ser alterado em:

```text
Configurações > Caminhos dos Viewers
```

Os perfis RealVNC ficam na pasta `realvnc` e seguem o formato:

```text
<Setor>_<Nome do Host>.vnc
```

Exemplo:

```text
Support_Workstation 01.vnc
```

Se o perfil não existir ou estiver vazio, o aplicativo informa o arquivo esperado.

## Credenciais e configurações por usuário

As credenciais são configuradas em:

```text
Configurações > Credenciais
```

Arquivos individuais ficam em:

```text
C:\Users\<usuario>\Documents\VNC-Menu\
├─ creds.json
├─ settings.json
└─ hosts.json
```

- `creds.json`: credenciais UltraVNC protegidas com Windows DPAPI.
- `settings.json`: preferências da interface, caminhos dos viewers, seleção atual e geometria das janelas.
- `hosts.json`: lista pessoal quando o modo **Personalizada** ou **Vazia** é usado.

Caso o Windows negue acesso de escrita a `Documents\VNC-Menu\settings.json`, o aplicativo utiliza:

```text
%APPDATA%\VNC-Menu\settings.json
```

como fallback para evitar falhas de inicialização.

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
- alterações na lista de hosts;
- mudanças de configuração;
- cópia de host/IP;
- abertura do compartilhamento `C$`;
- erros internos.

## Gerando o executável

Instale as dependências:

```bat
py -3 -m pip install -r requirements.txt
```

Exemplo com PyInstaller:

```bat
py -3 -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --clean ^
  --name "VNC-Menu" ^
  --contents-directory _internal ^
  --add-data "template.vnc;." ^
  --add-data "hosts.json;." ^
  "VNC-Menu.pyw"
```

Depois do build, os perfis RealVNC podem ser colocados em:

```text
dist\VNC-Menu\_internal\realvnc\
```

## Observações

- Atualmente, somente UltraVNC e RealVNC são suportados.
- Os viewers VNC não são incluídos no projeto.
- Credenciais protegidas por DPAPI não são compartilháveis diretamente entre usuários Windows.
- Reinício remoto, `qwinsta` e acesso a `C$` dependem das permissões e políticas do ambiente.
- Alterações na lista compartilhada podem afetar todos os usuários da mesma instalação.
- Arquivos como `creds.json`, `settings.json` e perfis sensíveis não devem ser versionados.

## Licença

Este projeto é distribuído sob a licença MIT. Consulte o arquivo [LICENSE](https://github.com/gabrielmariense/VNC-Menu/blob/main/LICENSE).
