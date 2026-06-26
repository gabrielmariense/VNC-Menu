# Contributing to VNC-Menu

## Português do Brasil

Obrigado por considerar uma contribuição.

O VNC-Menu é uma ferramenta simples para Windows feita para organizar conexões de acesso remoto. Mantenha as contribuições simples, genéricas e sem dados privados de ambiente.

### Sugestões

Use GitHub Issues para sugerir funcionalidades, reportar bugs ou tirar dúvidas.

Ao reportar um bug, inclua:

- o que aconteceu;
- o que você esperava;
- versão do Windows;
- versão do Python, se estiver rodando pelo código-fonte;
- viewer usado: `ultravnc` ou `realvnc`;
- mensagem de erro relevante, sem dados sensíveis.

### Contribuições

Boas contribuições incluem:

- melhorias na documentação;
- correções de bugs;
- melhorias nos textos da interface;
- melhorias no instalador/build;
- suporte a novos tipos de conexão;
- exemplos genéricos.

Atualmente, o VNC-Menu suporta somente:

- UltraVNC;
- RealVNC.

Se adicionar outro viewer, mantenha a implementação isolada em uma função própria e atualize o README.

### Não commite

Não commite dados privados ou sensíveis, incluindo:

- IPs ou hostnames reais;
- usuários ou senhas;
- `creds.json`;
- `settings.json`;
- logs de auditoria;
- perfis VNC exportados de ambientes reais.

---

## English

Thanks for considering a contribution.

VNC-Menu is a small Windows tool for organizing remote access connections. Keep contributions simple, generic and free of private environment data.

### Suggestions

Use GitHub Issues to suggest features, report bugs or ask questions.

When reporting a bug, include:

- what happened;
- what you expected;
- Windows version;
- Python version, if running from source;
- viewer used: `ultravnc` or `realvnc`;
- relevant error message, without sensitive data.

### Contributions

Good contributions include:

- documentation improvements;
- bug fixes;
- UI text improvements;
- installer/build improvements;
- support for new connection types;
- generic examples.

VNC-Menu currently supports only:

- UltraVNC;
- RealVNC.

If adding another viewer, keep it isolated in its own connection function and update the README.

### Do not commit

Do not commit private or sensitive data, including:

- real IPs or hostnames;
- usernames or passwords;
- `creds.json`;
- `settings.json`;
- audit logs;
- exported VNC profiles from real environments.
