#!/usr/bin/env python3

import os
import sys
import subprocess
import time
import getpass
from pathlib import Path

class ArchOstreeInstaller:
    def __init__(self):
        self.disk = "/dev/sda"
        self.hostname = "LiricoOS"
        self.username = "user"
        self.user_password = "password123"
        self.root_password = "root123"
        self.ostree_branch = "arch/stable/x86_64"
        self.work_dir = Path("/mnt/install")
        self.efi_partition = f"{self.disk}1"
        self.root_partition = f"{self.disk}2"
        self.home_partition = f"{self.disk}3"
        
    def run_command(self, cmd, check=True, capture=False, shell=True):
        """Выполнить команду с обработкой ошибок"""
        print(f"🚀 Выполняю: {cmd}")
        try:
            if capture:
                result = subprocess.run(cmd, shell=shell, check=check, 
                                      capture_output=True, text=True)
                return result.stdout.strip()
            else:
                subprocess.run(cmd, shell=shell, check=check)
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Ошибка при выполнении команды: {cmd}")
            print(f"Ошибка: {e}")
            if input("Продолжить установку? (y/N): ").lower() != 'y':
                sys.exit(1)
            return False

    def check_uefi(self):
        """Проверить режим UEFI"""
        print("🔍 Проверяю режим загрузки...")
        if os.path.exists("/sys/firmware/efi/efivars"):
            print("✅ Система в режиме UEFI")
            return True
        else:
            print("❌ Система не в режиме UEFI. Требуется UEFI для OSTree.")
            sys.exit(1)

    def get_disk_info(self):
        """Получить информацию о дисках"""
        print("💾 Доступные диски:")
        self.run_command("lsblk")
        
        disk = input(f"Выберите диск для установки (по умолчанию {self.disk}): ").strip()
        if disk:
            self.disk = disk
            self.efi_partition = f"{self.disk}1"
            self.root_partition = f"{self.disk}2"
            self.home_partition = f"{self.disk}3"
            
        print(f"Будет использован диск: {self.disk}")

    def get_user_info(self):
        """Получить информацию о пользователе"""
        self.hostname = input(f"Введите имя хоста (по умолчанию {self.hostname}): ").strip() or self.hostname
        self.username = input(f"Введите имя пользователя (по умолчанию {self.username}): ").strip() or self.username
        
        # Запрос паролей
        self.root_password = getpass.getpass("Введите пароль root: ") or self.root_password
        self.user_password = getpass.getpass(f"Введите пароль для пользователя {self.username}: ") or self.user_password

    def partition_disk(self):
        """Разметка диска"""
        print("💾 Размечаю диск...")
        
        # Очистка диска
        self.run_command(f"sgdisk -Z {self.disk}")
        time.sleep(2)
        
        # Создание разделов
        # ESP - 512M
        self.run_command(f"sgdisk -n 1:0:+512M -t 1:ef00 {self.disk}")
        # Root - 30G
        self.run_command(f"sgdisk -n 2:0:+30G -t 2:8304 {self.disk}")
        # Home - оставшееся место
        self.run_command(f"sgdisk -n 3:0:0 -t 3:8302 {self.disk}")
        
        # Синхронизация
        self.run_command(f"partprobe {self.disk}")
        time.sleep(1)
        
        # Форматирование разделов
        print("📝 Форматирую разделы...")
        self.run_command(f"mkfs.fat -F32 {self.efi_partition}")
        self.run_command(f"mkfs.btrfs -f {self.root_partition}")
        self.run_command(f"mkfs.btrfs -f {self.home_partition}")
        
        print("✅ Разметка диска завершена")

    def setup_btrfs(self):
        """Настройка Btrfs подсистем"""
        print("🗂️ Настраиваю Btrfs...")
        
        # Монтируем корневой раздел
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.run_command(f"mount {self.root_partition} {self.work_dir}")
        
        # Создаем субvolumes для корня
        subvolumes = ["@", "@home", "@ostree", "@var", "@tmp", "@log", "@snapshots"]
        for subvol in subvolumes:
            self.run_command(f"btrfs subvolume create {self.work_dir}/{subvol}")
        
        # Размонтируем
        self.run_command(f"umount {self.work_dir}")

    def mount_filesystems(self):
        """Монтирование файловых систем"""
        print("📂 Монтирую файловые системы...")
        
        # Монтируем корень с субvolumes
        mount_opts = "defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@"
        self.run_command(f"mount -o {mount_opts} {self.root_partition} {self.work_dir}")
        
        # Создаем необходимые директории
        directories = [
            self.work_dir / "home",
            self.work_dir / "ostree",
            self.work_dir / "var",
            self.work_dir / "tmp",
            self.work_dir / "var/log",
            self.work_dir / ".snapshots",
            self.work_dir / "boot/efi"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        
        # Монтируем остальные субvolumes
        mount_points = [
            (f"{self.root_partition}", f"defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@home", f"{self.work_dir}/home"),
            (f"{self.root_partition}", f"defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@ostree", f"{self.work_dir}/ostree"),
            (f"{self.root_partition}", f"defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@var", f"{self.work_dir}/var"),
            (f"{self.root_partition}", f"defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@tmp", f"{self.work_dir}/tmp"),
            (f"{self.root_partition}", f"defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@log", f"{self.work_dir}/var/log"),
            (f"{self.root_partition}", f"defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@snapshots", f"{self.work_dir}/.snapshots"),
            (f"{self.home_partition}", "defaults,noatime,compress=zstd,ssd,space_cache=v2", f"{self.work_dir}/home/{self.username}"),
            (f"{self.efi_partition}", "defaults", f"{self.work_dir}/boot/efi"),
        ]
        
        for device, options, mount_point in mount_points:
            self.run_command(f"mount -o {options} {device} {mount_point}")
        
        print("✅ Файловые системы смонтированы")

    def install_base_system(self):
        """Установка базовой системы"""
        print("📦 Устанавливаю базовую систему...")
        
        # Обновляем ключи
        self.run_command("pacman -Sy --noconfirm archlinux-keyring")
        
        # Устанавливаем базовые пакеты
        # base_packages = [
        #     "base", "base-devel", "linux", "linux-firmware",
        #     "btrfs-progs", "efibootmgr", "grub", "os-prober",
        #     "networkmanager", "sudo", "vim", "git", "curl", "wget",
        #     "bash-completion", "man-db", "man-pages", "texinfo",
        #     "chrony", "reflector", "fish", "zsh"
        # ]

        base_packages = [
            "base", "base-devel", "linux", "linux-firmware",
            "btrfs-progs", "efibootmgr", "grub", "os-prober",
            "networkmanager", "sudo", "vim", "nano", "git", "curl", "wget",
            "bash-completion", "man-db", "man-pages", "texinfo",
            "chrony", "reflector", "fish", "zsh", "distrobox", "flatpak"
        ]
        
        packages_cmd = " ".join(base_packages)
        self.run_command(f"pacstrap {self.work_dir} {packages_cmd}")
        
        print("✅ Базовая система установлена")

    def setup_fstab(self):
        """Генерация fstab"""
        print("📝 Генерирую fstab...")
        self.run_command(f"genfstab -U {self.work_dir} >> {self.work_dir}/etc/fstab")
        
        # Дополняем fstab опциями Btrfs
        with open(f"{self.work_dir}/etc/fstab", "a") as f:
            f.write("\n# Btrfs subvolumes\n")
            f.write(f"UUID={self.get_uuid(self.root_partition)} /home btrfs defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@home 0 0\n")
            f.write(f"UUID={self.get_uuid(self.root_partition)} /ostree btrfs defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@ostree 0 0\n")
            f.write(f"UUID={self.get_uuid(self.root_partition)} /var btrfs defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@var 0 0\n")
            f.write(f"UUID={self.get_uuid(self.root_partition)} /tmp btrfs defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@tmp 0 0\n")
            f.write(f"UUID={self.get_uuid(self.root_partition)} /var/log btrfs defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@log 0 0\n")
            f.write(f"UUID={self.get_uuid(self.root_partition)} /.snapshots btrfs defaults,noatime,compress=zstd,ssd,space_cache=v2,subvol=@snapshots 0 0\n")
        
        print("✅ fstab сгенерирован")

    def get_uuid(self, partition):
        """Получить UUID раздела"""
        cmd = ["blkid", "-s", "UUID", "-o", "value", partition]
        return self.run_command(cmd, capture=True, shell=False)

    def chroot_setup(self):
        """Настройка системы в chroot"""
        print("🔧 Настраиваю систему в chroot...")
        
        chroot_commands = [
            # Установка часового пояса
            "ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime",
            "hwclock --systohc",
            
            # Настройка локали
            "echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen",
            "echo 'ru_RU.UTF-8 UTF-8' >> /etc/locale.gen",
            "locale-gen",
            "echo 'LANG=en_US.UTF-8' > /etc/locale.conf",
            
            # Настройка сети
            f"echo '{self.hostname}' > /etc/hostname",
            
            # Создание hosts файла
            f"echo '127.0.0.1 localhost' >> /etc/hosts",
            f"echo '::1 localhost' >> /etc/hosts",
            f"echo '127.0.1.1 {self.hostname}.localdomain {self.hostname}' >> /etc/hosts",
            
            # Установка пароля root
            f"echo 'root:{self.root_password}' | chpasswd",
            
            # Настройка sudo
            "echo '%wheel ALL=(ALL) ALL' >> /etc/sudoers",
            "echo '%wheel ALL=(ALL) NOPASSWD: /usr/bin/btrfs' >> /etc/sudoers",
            
            # Включение служб
            "systemctl enable NetworkManager",
            "systemctl enable chronyd",
            "systemctl enable systemd-resolved"
        ]
        
        for cmd in chroot_commands:
            self.run_command(f"arch-chroot {self.work_dir} {cmd}")

    def create_user(self):
        """Создание пользователя"""
        print("👤 Создаю пользователя...")
        
        user_commands = [
            f"useradd -m -G wheel -s /bin/bash {self.username}",
            f"echo '{self.username}:{self.user_password}' | chpasswd",
            f"mkdir -p /home/{self.username}/.config",
            f"chown -R {self.username}:{self.username} /home/{self.username}"
        ]
        
        for cmd in user_commands:
            self.run_command(f"arch-chroot {self.work_dir} {cmd}")

    def install_ostree(self):
        """Установка и настройка OSTree"""
        print("🌳 Устанавливаю OSTree...")
        
        # Установка ostree и зависимостей
        ostree_packages = [
            "ostree", "rpm-ostree", "grub-btrfs", "systemd-container",
            "fuse-overlayfs", "podman", "skopeo"
        ]
        
        packages_cmd = " ".join(ostree_packages)
        self.run_command(f"arch-chroot {self.work_dir} pacman -S --noconfirm {packages_cmd}")
        
        # Инициализация ostree репозитория
        ostree_repo_dir = self.work_dir / "ostree/repo"
        ostree_repo_dir.mkdir(parents=True, exist_ok=True)
        
        self.run_command(f"arch-chroot {self.work_dir} ostree --repo=/ostree/repo init --mode=archive-z2")
        
        # Создание базового коммита
        self.create_ostree_commit()

    def create_ostree_commit(self):
        """Создание базового коммита OSTree"""
        print("📝 Создаю базовый коммит OSTree...")
        
        # Создаем временную директорию для коммита
        temp_dir = self.work_dir / "var/tmp/ostree-commit"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Копируем базовую систему (исключая специальные директории)
        exclude_dirs = ["ostree", "proc", "sys", "dev", "run", "tmp", "var/tmp", "boot/efi"]
        exclude_args = " ".join([f"--exclude=/{d}" for d in exclude_dirs])
        
        self.run_command(f"rsync -a {exclude_args} {self.work_dir}/ {temp_dir}/")
        
        # Очистка временных файлов
        self.run_command(f"rm -rf {temp_dir}/var/lib/pacman/*")
        self.run_command(f"rm -rf {temp_dir}/var/cache/pacman/*")
        self.run_command(f"rm -f {temp_dir}/etc/machine-id")
        
        # Создаем коммит
        commit_cmd = (
            f"arch-chroot {self.work_dir} ostree --repo=/ostree/repo commit "
            f"--branch={self.ostree_branch} "
            f"--tree=dir=/var/tmp/ostree-commit "
            f"--subject='Base Arch Linux with OSTree' "
            f"--body='Initial system commit with OSTree support'"
        )
        self.run_command(commit_cmd)
        
        # Очистка временной директории
        self.run_command(f"rm -rf {temp_dir}")
        
        print("✅ Базовый коммит OSTree создан")

    def install_flatpak(self):
        """Установка Flatpak"""
        print("📦 Устанавливаю Flatpak...")
        
        # Установка Flatpak
        # self.run_command(f"arch-chroot {self.work_dir} pacman -S --noconfirm flatpak flatpak-builder")
        
        # Настройка репозиториев Flatpak
        flatpak_commands = [
            "flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo",
            "flatpak update"
        ]
        
        for cmd in flatpak_commands:
            self.run_command(f"arch-chroot {self.work_dir} {cmd}")

    def install_kde(self):
        """Установка KDE Plasma"""
        print("🎨 Устанавливаю KDE Plasma...")
        
        kde_packages = [
            "plasma-meta", "kde-applications-meta", "sddm",
            "konsole", "dolphin", "kate", "firefox",
            "pipewire", "pipewire-pulse", "pipewire-alsa",
            "wireplumber", "sof-firmware", "xdg-desktop-portal",
            "xdg-desktop-portal-kde", "packagekit-qt5"
        ]
        
        packages_cmd = " ".join(kde_packages)
        self.run_command(f"arch-chroot {self.work_dir} pacman -S --noconfirm {packages_cmd}")
        
        # Включаем SDDM
        self.run_command(f"arch-chroot {self.work_dir} systemctl enable sddm")
        
        print("✅ KDE Plasma установлен")

    def install_flatpak_apps(self):
        """Установка популярных Flatpak приложений"""
        print("📱 Устанавливаю Flatpak приложения...")
        
        flatpak_apps = [
            "org.telegram.desktop",
            "com.spotify.Client", 
            "org.videolan.VLC",
            "com.visualstudio.code",
            "org.gimp.GIMP",
            "org.libreoffice.LibreOffice",
            "com.discordapp.Discord"
        ]
        
        for app in flatpak_apps:
            print(f"📥 Устанавливаю {app}...")
            self.run_command(f"arch-chroot {self.work_dir} flatpak install -y flathub {app}")

    def setup_bootloader(self):
        """Настройка загрузчика"""
        print("👢 Настраиваю загрузчик...")
        
        boot_commands = [
            "grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ARCH-OSTREE",
            "grub-mkconfig -o /boot/grub/grub.cfg"
        ]
        
        for cmd in boot_commands:
            self.run_command(f"arch-chroot {self.work_dir} {cmd}")

    def setup_snapper(self):
        """Настройка Snapper для создания снимков Btrfs"""
        print("📸 Настраиваю Snapper...")
        
        snapper_packages = ["snapper", "snap-pac", "grub-btrfs"]
        packages_cmd = " ".join(snapper_packages)
        self.run_command(f"arch-chroot {self.work_dir} pacman -S --noconfirm {packages_cmd}")
        
        # Конфигурация Snapper
        snapper_commands = [
            "snapper -c root create-config /",
            "snapper -c home create-config /home",
            "chmod a+rx /.snapshots",
            "chmod a+rx /home/.snapshots"
        ]
        
        for cmd in snapper_commands:
            self.run_command(f"arch-chroot {self.work_dir} {cmd}")

    def post_install_setup(self):
        """Пост-установочная настройка"""
        print("🎯 Выполняю финальную настройку...")
        
        # Настройка Wayland для KDE
        wayland_setup = [
            "echo 'XDG_SESSION_TYPE=wayland' >> /etc/environment",
            "echo 'QT_QPA_PLATFORM=wayland' >> /etc/environment", 
            "echo 'MOZ_ENABLE_WAYLAND=1' >> /etc/environment",
            "echo 'GTK_USE_PORTAL=1' >> /etc/environment"
        ]
        
        for cmd in wayland_setup:
            self.run_command(f"arch-chroot {self.work_dir} {cmd}")
        
        # Создание скрипта управления OSTree
        self.create_ostree_management_script()
        
        # Настройка Flatpak для пользователя
        self.run_command(f"arch-chroot {self.work_dir} sudo -u {self.username} flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo")

    def create_ostree_management_script(self):
        """Создание скрипта для управления OSTree"""
        script_content = '''#!/bin/bash
# OSTree Management Script
echo "🌳 OSTree Management"
echo "Available commands:"
echo "  ostree admin status          - Show current deployment"
echo "  ostree log arch/stable/x86_64 - Show commit history"
echo "  rpm-ostree status           - Show package updates"
echo "  snapper list                - List Btrfs snapshots"
echo "  flatpak list                - List installed Flatpaks"
echo "  flatpak update              - Update Flatpak applications"

# Useful aliases
alias ostree-status='ostree admin status'
alias flatpak-update='flatpak update -y'
alias snapper-list='snapper list'
'''
        
        script_path = self.work_dir / f"home/{self.username}/.bashrc_ostree"
        with open(script_path, 'w') as f:
            f.write(script_content)
        
        # Добавляем в .bashrc
        bashrc_path = self.work_dir / f"home/{self.username}/.bashrc"
        with open(bashrc_path, 'a') as f:
            f.write(f"\n# OSTree management\nsource ~/.bashrc_ostree\n")
        
        self.run_command(f"chmod +x {script_path}")
        self.run_command(f"chown {self.username}:{self.username} {script_path}")
        self.run_command(f"chown {self.username}:{self.username} {bashrc_path}")

    def cleanup(self):
        """Очистка после установки"""
        print("🧹 Выполняю очистку...")
        
        # Очистка кеша pacman
        self.run_command(f"arch-chroot {self.work_dir} pacman -Scc --noconfirm")
        
        # Размонтируем файловые системы в правильном порядке
        umount_points = [
            f"{self.work_dir}/boot/efi",
            f"{self.work_dir}/home/{self.username}",
            f"{self.work_dir}/var/log",
            f"{self.work_dir}/tmp", 
            f"{self.work_dir}/var",
            f"{self.work_dir}/ostree",
            f"{self.work_dir}/home",
            f"{self.work_dir}/.snapshots",
            f"{self.work_dir}"
        ]
        
        for point in umount_points:
            self.run_command(f"umount {point}", check=False)
        
        print("✅ Очистка завершена")

    def print_success(self):
        """Вывод информации об успешной установке"""
        print("\n" + "="*60)
        print("🎉 УСТАНОВКА ARCH LINUX С OSTREE ЗАВЕРШЕНА УСПЕШНО!")
        print("="*60)
        print(f"Хостнейм: {self.hostname}")
        print(f"Пользователь: {self.username}")
        print(f"Пароль root: {self.root_password}")
        print("\n📦 Установленные компоненты:")
        print("  ✅ Arch Linux с OSTree (immutable system)")
        print("  ✅ KDE Plasma Desktop Environment") 
        print("  ✅ Flatpak с Flathub репозиторием")
        print("  ✅ Btrfs с snapshots (Snapper)")
        print("  ✅ Wayland session для KDE")
        print("\n🚀 Полезные команды:")
        print("  ostree admin status    - Проверить статус OSTree")
        print("  flatpak list          - Список Flatpak приложений")
        print("  snapper list          - Список снимков системы")
        print("  rpm-ostree upgrade    - Обновить систему")
        print("\n📍 Следующие шаги:")
        print("  1. Перезагрузите систему: reboot")
        print("  2. Войдите в KDE Plasma")
        print("  3. Установите дополнительные Flatpak приложения")
        print("  4. Настройте систему под свои нужды")
        print("="*60)

    def run_installation(self):
        """Запуск полного процесса установки"""
        try:
            print("🚀 Arch Linux OSTree Installer")
            print("="*40)
            
            # Получение информации
            self.check_uefi()
            self.get_disk_info()
            self.get_user_info()
            
            # Подтверждение установки
            print(f"\n⚠️  Установка будет выполнена на диск: {self.disk}")
            print("ВСЕ ДАННЫЕ НА ДИСКЕ БУДУТ УДАЛЕНЫ!")
            confirm = input("Продолжить установку? (y/N): ").lower()
            if confirm != 'y':
                print("Установка отменена.")
                sys.exit(0)
            
            # Основные этапы установки
            steps = [
                ("Разметка диска", self.partition_disk),
                ("Настройка Btrfs", self.setup_btrfs),
                ("Монтирование ФС", self.mount_filesystems),
                ("Установка базовой системы", self.install_base_system),
                ("Настройка fstab", self.setup_fstab),
                ("Настройка в chroot", self.chroot_setup),
                ("Создание пользователя", self.create_user),
                ("Установка OSTree", self.install_ostree),
                ("Установка KDE", self.install_kde),
                ("Установка Flatpak", self.install_flatpak),
                ("Установка Flatpak приложений", self.install_flatpak_apps),
                ("Настройка Snapper", self.setup_snapper),
                ("Настройка загрузчика", self.setup_bootloader),
                ("Финальная настройка", self.post_install_setup),
                ("Очистка", self.cleanup)
            ]
            
            for step_name, step_func in steps:
                print(f"\n📍 Этап: {step_name}")
                start_time = time.time()
                step_func()
                elapsed_time = time.time() - start_time
                print(f"✅ Завершено за {elapsed_time:.1f} секунд")
                time.sleep(1)
            
            self.print_success()
            
        except KeyboardInterrupt:
            print("\n❌ Установка прервана пользователем")
            sys.exit(1)
        except Exception as e:
            print(f"\n💥 Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

def main():
    """Основная функция"""
    # Проверка прав root
    if os.geteuid() != 0:
        print("❌ Этот скрипт должен запускаться с правами root!")
        sys.exit(1)
    
    installer = ArchOstreeInstaller()
    installer.run_installation()

if __name__ == "__main__":
    main()