"""Tests for VNC-Menu-Updater.pyw.

safe_extract() is the only place in the project where a bug becomes a real
vulnerability: it unpacks an archive downloaded from the network. It is tested
here against traversal, absolute paths and symlink entries.
"""

import unittest
import zipfile
from pathlib import Path

import vncmenu_loader


class UpdaterTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # VNC-Menu-Updater.pyw may legitimately be absent (partial checkout, or
        # an overlay that only ships the changed files). Skip rather than error.
        if not vncmenu_loader.UPDATER_SCRIPT.is_file():
            raise unittest.SkipTest(
                f"{vncmenu_loader.UPDATER_SCRIPT.name} not present in this checkout"
            )
        cls.updater, cls.sandbox = vncmenu_loader.load_updater()

    @classmethod
    def tearDownClass(cls):
        vncmenu_loader.release_sandbox(getattr(cls, "sandbox", None))

    def _zip_with(self, entries, name):
        path = self.sandbox / name
        with zipfile.ZipFile(path, "w") as archive:
            for arcname, data in entries:
                archive.writestr(arcname, data)
        return path


class TestPreservedPaths(UpdaterTestCase):
    def test_user_data_is_preserved(self):
        for relative in (
            "data/hosts.json",
            "data/template.vnc",
            "data/realvnc/Setor_PC01.vnc",
            "logs/user.log",
            "_internal/hosts.json",
            "_internal/realvnc/x.vnc",
        ):
            self.assertTrue(
                self.updater.is_preserved(Path(relative)), relative
            )

    def test_application_files_are_not_preserved(self):
        for relative in ("VNC-Menu.pyw", "VNC-Menu-Updater.pyw", "_internal/base_library.zip"):
            self.assertFalse(self.updater.is_preserved(Path(relative)), relative)


class TestSafeExtract(UpdaterTestCase):
    def test_benign_archive_extracts(self):
        archive = self._zip_with(
            [("VNC-Menu.pyw", "print('hi')"), ("sub/dir/file.txt", "ok")], "benign.zip"
        )
        destination = self.sandbox / "out-benign"
        destination.mkdir()
        self.updater.safe_extract(archive, destination)
        self.assertTrue((destination / "VNC-Menu.pyw").is_file())
        self.assertTrue((destination / "sub" / "dir" / "file.txt").is_file())

    def test_parent_traversal_is_rejected(self):
        archive = self._zip_with([("../escaped.txt", "x")], "traversal.zip")
        destination = self.sandbox / "out-traversal"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)
        self.assertFalse((self.sandbox / "escaped.txt").exists())

    def test_backslash_traversal_is_rejected(self):
        archive = self._zip_with([("..\\escaped-win.txt", "x")], "traversal-win.zip")
        destination = self.sandbox / "out-traversal-win"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)

    def test_absolute_path_is_rejected(self):
        archive = self._zip_with([("/tmp/absolute-evil.txt", "x")], "absolute.zip")
        destination = self.sandbox / "out-absolute"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)

    def test_symlink_entry_is_rejected(self):
        path = self.sandbox / "symlink.zip"
        with zipfile.ZipFile(path, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777 << 16)  # S_IFLNK
            archive.writestr(info, "/etc/passwd")
        destination = self.sandbox / "out-symlink"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(path, destination)

    def test_nothing_is_written_when_a_bad_entry_is_present(self):
        """Validation runs over every entry before extractall()."""
        archive = self._zip_with(
            [("good.txt", "ok"), ("../bad.txt", "evil")], "mixed.zip"
        )
        destination = self.sandbox / "out-mixed"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)
        self.assertEqual(list(destination.iterdir()), [])


class TestFindPackageRoot(UpdaterTestCase):
    def _pacote(self, pasta):
        """Ponto de entrada mais a pasta vncmenu\\, que todo pacote valido tem."""
        pasta.mkdir(parents=True, exist_ok=True)
        principal = pasta / "VNC-Menu.pyw"
        principal.write_text("x", encoding="utf-8")
        (pasta / "vncmenu").mkdir(exist_ok=True)
        (pasta / "vncmenu" / "__init__.py").write_text("x", encoding="utf-8")
        return principal

    def test_finds_the_requested_entry_point(self):
        staging = self.sandbox / "staging-a"
        main = self._pacote(staging / "VNC-Menu-v1.7.0")

        root, found = self.updater.find_package_root(staging, "VNC-Menu.pyw")
        self.assertEqual(found, main)
        self.assertEqual(root, main.parent)

    def test_prefers_the_shallowest_candidate(self):
        staging = self.sandbox / "staging-b"
        shallow = self._pacote(staging)
        self._pacote(staging / "a" / "b")

        _root, found = self.updater.find_package_root(staging, "VNC-Menu.pyw")
        self.assertEqual(found, shallow)

    def test_raises_when_the_package_has_no_entry_point(self):
        staging = self.sandbox / "staging-c"
        staging.mkdir()
        (staging / "readme.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.updater.find_package_root(staging, "VNC-Menu.pyw")


if __name__ == "__main__":
    unittest.main()


class TestPackageLayouts(UpdaterTestCase):
    """O ZIP de release pode vir em tres formatos, e os tres tem de instalar
    nos mesmos lugares. Um pacote malformado tem de ser recusado, nao
    instalado pela metade."""

    def _instalar(self, entradas, nome):
        import shutil
        archive = self._zip_with(entradas, nome)
        staging = self.sandbox / (nome + "-staging")
        staging.mkdir(exist_ok=True)
        self.updater.safe_extract(archive, staging)

        instalado = self.sandbox / (nome + "-install")
        shutil.rmtree(instalado, ignore_errors=True)
        (instalado / "vncmenu").mkdir(parents=True)
        (instalado / "VNC-Menu.pyw").write_text("antigo", encoding="utf-8")

        raiz, _principal = self.updater.find_package_root(staging, "VNC-Menu.pyw")
        backup = self.sandbox / (nome + "-backup")
        backup.mkdir(exist_ok=True)
        self.updater.copy_update_files(raiz, instalado, backup)

        return sorted(
            str(caminho.relative_to(instalado)).replace("\\", "/")
            for caminho in instalado.rglob("*") if caminho.is_file()
        )

    ESPERADO = ["VNC-Menu-Updater.pyw", "VNC-Menu.pyw",
                "vncmenu/__init__.py", "vncmenu/config.py", "vncmenu/ui/app.py"]

    def _conteudo(self, prefixo=""):
        return [
            (prefixo + "VNC-Menu.pyw", "novo"),
            (prefixo + "VNC-Menu-Updater.pyw", "novo"),
            (prefixo + "vncmenu/__init__.py", "novo"),
            (prefixo + "vncmenu/config.py", "novo"),
            (prefixo + "vncmenu/ui/app.py", "novo"),
        ]

    def test_a_folder_at_the_top_installs_correctly(self):
        # O que o CREATE-UPDATE-PACKAGE.ps1 gera.
        self.assertEqual(self._instalar(self._conteudo("VNC-Menu/"), "a"),
                         self.ESPERADO)

    def test_a_flat_archive_installs_correctly(self):
        self.assertEqual(self._instalar(self._conteudo(), "b"), self.ESPERADO)

    def test_a_github_source_archive_installs_correctly(self):
        self.assertEqual(self._instalar(self._conteudo("VNC-Menu-2.5.1/"), "c"),
                         self.ESPERADO)

    def test_the_package_never_flattens_the_module_folder(self):
        # A falha relatada: modulos de vncmenu\\ indo parar na raiz da
        # instalacao. Nenhum layout valido pode produzir isso.
        for prefixo, nome in (("VNC-Menu/", "d"), ("", "e"), ("VNC-Menu-2.5.1/", "f")):
            instalados = self._instalar(self._conteudo(prefixo), nome)
            self.assertNotIn("config.py", instalados, prefixo)
            self.assertIn("vncmenu/config.py", instalados, prefixo)

    def test_a_package_without_the_module_folder_is_refused(self):
        # ZIP com o conteudo de vncmenu\\ solto ao lado do ponto de entrada.
        archive = self._zip_with([
            ("VNC-Menu.pyw", "novo"),
            ("config.py", "novo"),
            ("remote.py", "novo"),
        ], "malformado.zip")
        staging = self.sandbox / "malformado-staging"
        staging.mkdir(exist_ok=True)
        self.updater.safe_extract(archive, staging)

        with self.assertRaises(RuntimeError) as capturado:
            self.updater.find_package_root(staging, "VNC-Menu.pyw")
        self.assertIn("vncmenu", str(capturado.exception))


class TestBackslashArchives(UpdaterTestCase):
    """ZIP gravado com contrabarra no nome das entradas.

    O Compress-Archive do Windows PowerShell 5.1 faz isso, contrariando a
    especificacao do formato (APPNOTE 4.4.17.1 exige barra normal). O
    extractall() so acerta esses nomes no Windows, onde os.sep e a
    contrabarra e ele parte por ali; em qualquer outro sistema o caminho
    inteiro vira UM nome de arquivo e o pacote sai achatado.
    """

    def _zip_com_contrabarra(self, nome):
        import zipfile
        caminho = self.sandbox / nome
        with zipfile.ZipFile(caminho, "w") as archive:
            for arcname in (
                "VNC-Menu\\VNC-Menu.pyw",
                "VNC-Menu\\VNC-Menu-Updater.pyw",
                "VNC-Menu\\vncmenu\\__init__.py",
                "VNC-Menu\\vncmenu\\config.py",
                "VNC-Menu\\vncmenu\\ui\\app.py",
            ):
                archive.writestr(arcname, "novo")
        return caminho

    def test_it_extracts_into_real_folders(self):
        staging = self.sandbox / "contrabarra-staging"
        staging.mkdir(exist_ok=True)
        self.updater.safe_extract(self._zip_com_contrabarra("cb.zip"), staging)

        extraidos = sorted(
            str(p.relative_to(staging)).replace("\\", "/")
            for p in staging.rglob("*") if p.is_file()
        )
        self.assertEqual(extraidos, [
            "VNC-Menu/VNC-Menu-Updater.pyw",
            "VNC-Menu/VNC-Menu.pyw",
            "VNC-Menu/vncmenu/__init__.py",
            "VNC-Menu/vncmenu/config.py",
            "VNC-Menu/vncmenu/ui/app.py",
        ])

    def test_nothing_is_written_as_one_flat_name(self):
        staging = self.sandbox / "contrabarra-plano"
        staging.mkdir(exist_ok=True)
        self.updater.safe_extract(self._zip_com_contrabarra("cb2.zip"), staging)
        for caminho in staging.rglob("*"):
            self.assertNotIn("\\", caminho.name,
                             f"{caminho.name} virou um nome so, achatado")

    def test_such_an_archive_still_installs_correctly(self):
        import shutil
        staging = self.sandbox / "contrabarra-inst-staging"
        staging.mkdir(exist_ok=True)
        self.updater.safe_extract(self._zip_com_contrabarra("cb3.zip"), staging)

        instalado = self.sandbox / "contrabarra-install"
        shutil.rmtree(instalado, ignore_errors=True)
        instalado.mkdir()
        raiz, _ = self.updater.find_package_root(staging, "VNC-Menu.pyw")
        backup = self.sandbox / "contrabarra-backup"
        backup.mkdir(exist_ok=True)
        self.updater.copy_update_files(raiz, instalado, backup)

        finais = sorted(
            str(p.relative_to(instalado)).replace("\\", "/")
            for p in instalado.rglob("*") if p.is_file()
        )
        self.assertIn("vncmenu/config.py", finais)
        self.assertNotIn("config.py", finais)
