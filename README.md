# VNC-Menu

Interface gráfica para Windows que organiza e abre conexões VNC a partir de uma lista estruturada de hosts.

O objetivo do projeto é facilitar o acesso rápido a várias máquinas, evitando a abertura manual de diversos perfis VNC e reduzindo a repetição de credenciais no dia a dia.

## Funcionalidades

- Interface desktop em Tkinter para Windows.
- Organização de hosts por **Unidade > Setor > Host**.
- Suporte atual somente a **UltraVNC** e **RealVNC**.
- Conexões UltraVNC usando um `template.vnc` compartilhado.
- Conexões RealVNC usando arquivos de perfil `.vnc`.
- Credenciais por usuário criptografadas com Windows DPAPI.
- Configurações individuais por usuário.
- Listas de hosts compartilhadas ou pessoais.
- Seleção da lista de hosts no primeiro uso: **Padrão**, **Personalizada** ou **Vazia**.
- Aviso antes de editar a lista compartilhada.
- Ação opcional para reiniciar hosts.
- Consulta de usuário/sessão logada usando `qwinsta`.
- Logs de auditoria por usuário na pasta `logs` do aplicativo.
- Modo escuro.
- Estrutura compatível com PyInstaller.

## Requisitos

- Windows.
- Python 3.12 ou superior.
- UltraVNC Viewer instalado para conexões UltraVNC.
- RealVNC Viewer instalado para conexões RealVNC.
- Pacotes Python listados em `requirements.txt`.

Dependências atuais:

```txt
pywinauto==0.6.9
pyinstaller>=6.0,<7.0
pywin32>=306
comtypes>=1.4.0
```

## Instalação

Clone o repositório e execute:

```bat
INSTALAR.bat
```

O instalador verifica se o Python está disponível, tenta instalar pelo `winget` caso esteja ausente, atualiza o `pip`, instala as dependências e valida os imports principais.

Instalação manual:

```bat
py -3 -m pip install -r requirements.txt
```

Executar em modo script:

```bat
py -3 VNC-Menu-v5.pyw
```

## Estrutura recomendada

```text
VNC-Menu/
├─ VNC-Menu-v5.pyw
├─ requirements.txt
├─ INSTALAR.bat
├─ template.vnc
├─ hosts.json
├─ realvnc/
│  └─ exemplo-perfil.vnc
└─ logs/
   └─ <usuario-windows>.log
```

Quando empacotado com PyInstaller, os dados do aplicativo ficam dentro de `_internal`:

```text
VNC-Menu/
├─ VNC-Menu.exe
└─ _internal/
   ├─ hosts.json
   ├─ template.vnc
   └─ realvnc/
```

Arquivos por usuário:

```text
C:\Users\<usuario>\Documents\VNC-Menu\
├─ creds.json
├─ settings.json
└─ hosts.json
```

Logs por usuário:

```text
.\logs\<usuario-windows>.log
.\logs\<usuario-windows>_error.log
```

## Formato do hosts.json

A lista de hosts usa uma estrutura JSON baseada em unidades, setores e hosts.

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

Se `viewer` for omitido ou inválido, o app usa `ultravnc` como padrão.

## UltraVNC

Caminho esperado do UltraVNC Viewer:

```text
C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe
```

O app usa um arquivo `template.vnc` na pasta de dados do aplicativo. Esse template é copiado para um arquivo temporário, o host de destino é inserido e o UltraVNC é iniciado a partir desse perfil temporário.

## RealVNC

Caminho esperado do RealVNC Viewer:

```text
C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe
```

Os perfis RealVNC devem ficar na pasta `realvnc`.

Formato esperado:

```text
<Setor>_<Nome do Host>.vnc
```

Exemplo:

```text
Support_Workstation 01.vnc
```

Se o perfil não existir ou estiver vazio, o app mostra uma janela com opções para criar o arquivo ou copiar o nome esperado.

## Credenciais

As credenciais são configuradas em:

```text
Configurações > Credenciais
```

Elas são salvas por usuário em:

```text
Documents\VNC-Menu\creds.json
```

As senhas são criptografadas com Windows DPAPI. Isso vincula o arquivo de credenciais ao usuário Windows que criou a senha.

## Modos da lista de hosts

### Padrão

Usa o `hosts.json` compartilhado da pasta do aplicativo.

Indicado quando todos os usuários da mesma instalação devem usar a mesma lista.

### Personalizada

Copia o `hosts.json` compartilhado para `Documents\VNC-Menu`.

Indicado quando o usuário precisa editar sua própria lista sem afetar outros usuários.

### Vazia

Cria uma lista pessoal a partir da estrutura padrão do script.

Indicado para iniciar uma configuração limpa.

## Logs de auditoria

O app grava logs por usuário em:

```text
.\logs\<usuario-windows>.log
```

Ações registradas incluem:

- início do aplicativo;
- seleção ou troca da lista de hosts;
- escolha feita no aviso de edição da lista compartilhada;
- tentativas e início de conexão VNC;
- tentativas de reinício;
- comando de reinício enviado ou erro;
- consultas de usuários logados;
- alterações em unidades, setores e hosts;
- salvamento da lista de hosts;
- renomeação de perfis RealVNC.

Exemplo:

```text
[2026-06-25 09:30:12] user=john action=CONNECTION_ATTEMPT details=viewer=UltraVNC; name=Workstation 01; host=192.168.1.10; setor=Support
```

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
  "VNC-Menu-v5.pyw"
```

Depois do build, coloque os perfis RealVNC em:

```text
dist\VNC-Menu\_internal\realvnc\
```

## Observações

- Atualmente, somente UltraVNC e RealVNC são suportados.
- Os viewers VNC não são incluídos no projeto.
- Credenciais não são compartilhadas entre usuários Windows.
- Alterações na lista compartilhada afetam todos os usuários que utilizam a mesma pasta do aplicativo.
- A ação de reiniciar hosts depende das permissões do Windows e da política da rede.
- A consulta com `qwinsta` depende de permissão para consultar sessões remotas no Windows.

## Licença

Defina uma licença antes de publicar o projeto.
