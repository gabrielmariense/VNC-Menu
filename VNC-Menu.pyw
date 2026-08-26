"""VNC-Menu — ponto de entrada.

Este arquivo precisa manter exatamente este nome e permanecer na raiz da
instalação:

  * SCRIPT_DIR (vncmenu/config.py) ancora data/ e logs/ nele;
  * o atualizador o recebe em --main-entry e o relança pelo nome;
  * find_package_root() procura por ele dentro do ZIP da release.

Todo o código está em vncmenu/.
"""

import sys
from pathlib import Path
from tkinter import messagebox

# Garante que o pacote seja encontrado mesmo quando o processo é iniciado a
# partir de outro diretório de trabalho.
sys.path.insert(0, str(Path(__file__).resolve().parent))


if __name__ == "__main__":
    try:
        from vncmenu.ui.app import main

        main()
    except Exception as exc:
        detail = ""
        try:
            from vncmenu.applog import log_exception
            from vncmenu.config import ERROR_LOG

            log_exception(exc)
            detail = f"\n\nLog: {ERROR_LOG}"
        except Exception:
            pass
        messagebox.showerror("Erro", f"O app falhou ao iniciar:\n{exc}{detail}")
