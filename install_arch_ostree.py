#!/usr/bin/env python3
"""
Arch Linux OSTree Installer with Flatpak & Distrobox
Автоматизированная установка атомарного Arch Linux
"""

import os
import sys
import subprocess
import shutil
import argparse
import configparser
from pathlib import Path
import logging
import tempfile

class ArchOstreeInstaller:
    def __init__(self, config_file=None):
        self.setup_logging()
        self.config = self.load_config(config_file)
        self.ostree_repo = Path("/ostree/repo")
        self.deploy_path = Path("/mnt/ostree-deploy")
        
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('/tmp/arch-ostree-install.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.log = logging.getLogger(__name__)
        
    def load_config(self, config_file):
        """Загрузка конфигурации"""
        config = configparser.ConfigParser()
        
        # Конфигурация по умолчанию
        config['DEFAULT'] = {
            'hostname': 'arch-ostree',
            'username': 'user',
            'timezone': 'Europe/Moscow',
            'locale': 'en_US.UTF-8',
            'keymap': 'us',
            'bootloader': 'systemd-boot',
            'ostree_branch': 'arch/linux/x86_64'
        }
        
        config['PACKAGES'] = {
            'base': 'base base-devel linux linux-firmware',
            'network': 'networkmanager iwd',
            'utils': 'sudo nano vim git curl wget',
            'flatpak': 'flatpak',
            'distrobox': 'distrobox podman toolbox'
        }
        
        config['FLATPAK'] = {
            'apps': 'org.mozilla.firefox org.videolan.VLC org.gimp.GIMP org.libreoffice.LibreOffice org.telegram.desktop com.github.tchx84.Flatseal'
        }
        
        if config_file and Path(config_file).exists():
            config.read(config_file)
            
        return config
        
    def run_command(self, cmd, check=True, capture_output=False, **kwargs):
        """Выполнение команды с логированием"""
        self.log.info(f"Выполнение: {cmd}")
        
        if capture_output:
            result = subprocess.run(cmd, shell=True, check=check, 
                                  capture_output=True, text=True, **kwargs)
        else:
            result = subprocess.run(cmd, shell=True, check=check, **kwargs)
            
        return result
        
    def check_prerequisites(self):
        """Проверка предварительных условий"""
        self.log.info("Проверка предварительных условий...")
        
        # Проверка UEFI
        if not Path("/sys/firmware/efi").exists():
            self.log.error("Требуется UEFI система")
            return False
            
        # Проверка интернета
        try:
            self.run_command("ping -c 1 archlinux.org", check=True)
        except subprocess.CalledProcessError:
            self.log.error("Нет подключения к интернету")
            return False
            
        # Проверка свободного места
        stat = shutil.disk_usage("/")
        if stat.free < 10 * 1024 * 1024 * 1024:  # 10GB
            self.log.error("Требуется минимум 10GB свободного места")
            return False
            
        return True
        
    def setup_disks(self, disk):
        """Настройка дисков с btrfs для OSTree"""
        self.log.info(f"Настройка диска {disk}...")
        
        # Разметка диска
        commands = [
            f"parted -s {disk} mklabel gpt",
            f"parted -s {disk} mkpart primary fat32 1MiB 513MiB",
            f"parted -s {disk} set 1 esp on",
            f"parted -s {disk} mkpart primary btrfs 513MiB 100%"
        ]
        
        for cmd in commands:
            self.run_command(cmd)
            
        # Форматирование разделов
        self.run_command(f"mkfs.fat -F32 {disk}1")
        self.run_command(f"mkfs.btrfs -f {disk}2")
        
        # Монтирование
        self.deploy_path.mkdir(parents=True, exist_ok=True)
        self.run_command(f"mount {disk}2 {self.deploy_path}")
        self.run_command(f"mkdir -p {self.deploy_path}/boot")
        self.run_command(f"mount {disk}1 {self.deploy_path}/boot")
        
    def create_ostree_repo(self):
        """Создание OSTree репозитория"""
        self.log.info("Создание OSTree репозитория...")
        
        repo_path = self.deploy_path / "ostree/repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        
        self.run_command(f"ostree --repo={repo_path} init --mode=bare-user")
        
    def create_base_system(self):
        """Создание базовой системы Arch"""
        self.log.info("Создание базовой системы...")
        
        # Установка базовых пакетов
        base_packages = self.config['PACKAGES']['base']
        network_packages = self.config['PACKAGES']['network']
        utils_packages = self.config['PACKAGES']['utils']
        
        all_packages = f"{base_packages} {network_packages} {utils_packages}"
        
        self.run_command(f"pacstrap -c {self.deploy_path} {all_packages}")
        
    def configure_system(self):
        """Базовая настройка системы"""
        self.log.info("Настройка системы...")
        
        # Fstab
        self.run_command(f"genfstab -U {self.deploy_path} >> {self.deploy_path}/etc/fstab")
        
        # Chroot настройки
        chroot_cmds = [
            f"arch-chroot {self.deploy_path} ln -sf /usr/share/zoneinfo/{self.config['DEFAULT']['timezone']} /etc/localtime",
            f"arch-chroot {self.deploy_path} hwclock --systohc",
            
            # Локали
            f"echo '{self.config['DEFAULT']['locale']} UTF-8' >> {self.deploy_path}/etc/locale.gen",
            f"echo 'LANG={self.config['DEFAULT']['locale']}' > {self.deploy_path}/etc/locale.conf",
            f"arch-chroot {self.deploy_path} locale-gen",
            
            # Keyboard
            f"echo 'KEYMAP={self.config['DEFAULT']['keymap']}' > {self.deploy_path}/etc/vconsole.conf",
            
            # Hostname
            f"echo '{self.config['DEFAULT']['hostname']}' > {self.deploy_path}/etc/hostname",
            
            # Hosts
            f"echo '127.0.0.1 localhost' >> {self.deploy_path}/etc/hosts",
            f"echo '::1 localhost' >> {self.deploy_path}/etc/hosts",
            f"echo '127.0.1.1 {self.config['DEFAULT']['hostname']}.localdomain {self.config['DEFAULT']['hostname']}' >> {self.deploy_path}/etc/hosts",
            
            # Пользователь
            f"arch-chroot {self.deploy_path} useradd -m -G wheel -s /bin/bash {self.config['DEFAULT']['username']}",
            f"echo '%wheel ALL=(ALL:ALL) ALL' >> {self.deploy_path}/etc/sudoers",
            
            # Пароль root
            f"echo 'root:password' | arch-chroot {self.deploy_path} chpasswd",
            
            # Сетевой менеджер
            f"arch-chroot {self.deploy_path} systemctl enable NetworkManager",
        ]
        
        for cmd in chroot_cmds:
            self.run_command(cmd)
            
    def create_ostree_commit(self):
        """Создание OSTree коммита из базовой системы"""
        self.log.info("Создание OSTree коммита...")
        
        repo_path = self.deploy_path / "ostree/repo"
        branch = self.config['DEFAULT']['ostree_branch']
        
        # Коммит системы
        self.run_command(
            f"ostree --repo={repo_path} commit "
            f"--branch={branch} "
            f"--tree=dir={self.deploy_path} "
            f"--add-metadata-string=version=1.0.0"
        )
        
    def setup_bootloader(self):
        """Установка загрузчика"""
        self.log.info("Установка загрузчика...")
        
        if self.config['DEFAULT']['bootloader'] == 'systemd-boot':
            self.setup_systemd_boot()
        else:
            self.log.error("Поддерживается только systemd-boot")
            
    def setup_systemd_boot(self):
        """Настройка systemd-boot"""
        boot_path = self.deploy_path / "boot"
        
        # Установка bootloader
        self.run_command(f"bootctl --path={boot_path} install")
        
        # Создание конфигурации
        loader_conf = boot_path / "loader/loader.conf"
        loader_conf.parent.mkdir(parents=True, exist_ok=True)
        
        with open(loader_conf, 'w') as f:
            f.write("default arch-ostree\n")
            f.write("timeout 5\n")
            f.write("console-mode keep\n")
            
        # Создание записи для загрузки
        entries_path = boot_path / "loader/entries"
        entries_path.mkdir(exist_ok=True)
        
        entry_file = entries_path / "arch-ostree.conf"
        with open(entry_file, 'w') as f:
            f.write("""title Arch Linux OSTree
linux /vmlinuz-linux
initrd /initramfs-linux.img
options root=LABEL=arch-ostree rw rootflags=subvol=@ ostree=/ostree/boot.1/arch/linux/x86_64/0
""")
        
    def install_flatpak_distrobox(self):
        """Установка Flatpak и Distrobox в систему"""
        self.log.info("Установка Flatpak и Distrobox...")
        
        # Установка пакетов
        flatpak_pkgs = self.config['PACKAGES']['flatpak']
        distrobox_pkgs = self.config['PACKAGES']['distrobox']
        
        self.run_command(f"arch-chroot {self.deploy_path} pacman -S --noconfirm {flatpak_pkgs} {distrobox_pkgs}")
        
        # Настройка Flatpak
        self.run_command(f"arch-chroot {self.deploy_path} flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo")
        
        # Настройка Podman для пользователя
        self.run_command(f"arch-chroot {self.deploy_path} systemctl enable --now podman.socket")
        
    def create_ostree_deployment(self):
        """Создание развертывания OSTree"""
        self.log.info("Создание развертывания OSTree...")
        
        repo_path = self.deploy_path / "ostree/repo"
        branch = self.config['DEFAULT']['ostree_branch']
        
        # Развертывание системы
        self.run_command(
            f"ostree admin deploy --sysroot={self.deploy_path} "
            f"--os=arch {branch}"
        )
        
    def post_install_setup(self):
        """Пост-установочная настройка"""
        self.log.info("Пост-установочная настройка...")
        
        # Создание скрипта для управления обновлениями
        update_script = self.deploy_path / "usr/local/bin/ostree-update"
        update_script.parent.mkdir(parents=True, exist_ok=True)
        
        with open(update_script, 'w') as f:
            f.write("""#!/bin/bash
# OSTree System Update Script
set -e

echo "Проверка обновлений..."
if ostree admin status | grep -q "pending"; then
    echo "Есть ожидающие обновления"
    read -p "Применить обновления? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo ostree admin upgrade
        echo "Обновление применено. Перезагрузите систему."
    fi
else
    echo "Обновлений не найдено"
fi
""")
        
        self.run_command(f"chmod +x {update_script}")
        
    def install(self, disk):
        """Основной метод установки"""
        try:
            self.log.info("Начало установки Arch Linux с OSTree")
            
            if not self.check_prerequisites():
                sys.exit(1)
                
            self.setup_disks(disk)
            self.create_ostree_repo()
            self.create_base_system()
            self.configure_system()
            self.install_flatpak_distrobox()
            self.create_ostree_commit()
            self.create_ostree_deployment()
            self.setup_bootloader()
            self.post_install_setup()
            
            self.log.info("Установка завершена успешно!")
            self.log.info("Перезагрузите систему для входа в новую среду")
            
        except Exception as e:
            self.log.error(f"Ошибка установки: {e}")
            sys.exit(1)
            
    def create_config(self, output_file="ostree-install.conf"):
        """Создание конфигурационного файла"""
        config = configparser.ConfigParser()
        
        config['DEFAULT'] = {
            'hostname': 'my-arch-ostree',
            'username': 'myuser', 
            'timezone': 'Europe/Moscow',
            'locale': 'en_US.UTF-8',
            'keymap': 'us',
            'bootloader': 'systemd-boot',
            'ostree_branch': 'arch/linux/x86_64'
        }
        
        config['PACKAGES'] = {
            'base': 'base base-devel linux linux-firmware',
            'network': 'networkmanager iwd',
            'utils': 'sudo nano vim git curl wget',
            'flatpak': 'flatpak',
            'distrobox': 'distrobox podman toolbox'
        }
        
        config['FLATPAK'] = {
            'apps': 'org.mozilla.firefox org.videolan.VLC org.gimp.GIMP org.libreoffice.LibreOffice'
        }
        
        with open(output_file, 'w') as f:
            config.write(f)
            
        self.log.info(f"Конфигурационный файл создан: {output_file}")

def main():
    parser = argparse.ArgumentParser(description='Arch Linux OSTree Installer')
    parser.add_argument('disk', help='Target disk (e.g., /dev/sda)')
    parser.add_argument('--config', help='Configuration file')
    parser.add_argument('--create-config', help='Create sample config file')
    
    args = parser.parse_args()
    
    installer = ArchOstreeInstaller(args.config)
    
    if args.create_config:
        installer.create_config(args.create_config)
        return
        
    if not args.disk:
        parser.print_help()
        return
        
    # Подтверждение
    print(f"ВНИМАНИЕ: Это сотрет все данные на диске {args.disk}!")
    confirm = input("Продолжить? (yes/NO): ")
    
    if confirm.lower() != 'yes':
        print("Установка отменена")
        return
        
    installer.install(args.disk)

if __name__ == "__main__":
    main()