#!/usr/bin/env bash
# Build on Ubuntu 24.04 amd64. The receiver checkout stays at the pinned tree.
set -euo pipefail
commit=3132713b88a1b5b2ee8291bff8076574749349de
test "$(git -C upstream rev-parse HEAD)" = "$commit"
test "$(git -C upstream rev-parse HEAD^{tree})" = a79f60ccdddd94a4a928906b32c2c02e3398011a
git -C upstream diff --exit-code HEAD
sudo apt-get update -q
sudo apt-get install -y --no-install-recommends ninja-build cmake libboost-dev \
  libboost-date-time-dev libboost-system-dev libboost-filesystem-dev libboost-thread-dev \
  libboost-chrono-dev libboost-serialization-dev liblog4cpp5-dev gnuradio-dev gr-osmosdr \
  libpugixml-dev libpcap-dev libblas-dev liblapack-dev libarmadillo-dev libgflags-dev \
  libgoogle-glog-dev libunwind-dev libgnutls-openssl-dev libmatio-dev protobuf-compiler \
  libprotobuf-dev python3-mako liborc-0.4-dev busybox-static sshfs openssh-client sshpass \
  linux-image-virtual cpio kmod zstd
cmake -S upstream -B receiver-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_UNIT_TESTING=OFF -DENABLE_SYSTEM_TESTING=OFF -DENABLE_GNSS_SIM_INSTALL=OFF
cmake --build receiver-build --target gnss-sdr --parallel 3
git -C upstream diff --exit-code HEAD
mkdir -p guest-output guest-root/{bin,sbin,etc,dev,proc,sys,tmp,root,mnt,run,usr/bin}
exe="$(find receiver-build upstream/install -type f -executable -name gnss-sdr -print -quit)"
test -x "$exe"
lnroot="$PWD/guest-root"
copy_elf() {
  local input="$1" destination="$2" dep
  install -D "$input" "$lnroot/$destination"
  while read -r dep; do
    install -D "$dep" "$lnroot/$dep"
  done < <(ldd "$input" | awk '/=> \// {print $3} /^[[:space:]]*\// {print $1}' | sort -u)
}
copy_elf "$exe" usr/bin/gnss-sdr
# Upstream's uninstalled executable may resolve bundled VOLK via a build-tree RUNPATH.
while read -r soname dep; do install -D "$dep" "$lnroot/usr/lib/$soname"; done \
  < <(ldd "$exe" | awk '/=> \// && /receiver-build|\/upstream\// {print $1,$3}')
install -D /bin/busybox "$lnroot/bin/busybox"
for cmd in sh mount mkdir cat sleep poweroff ip ln chmod modprobe cp ls env grep sed basename; do
  ln -s busybox "$lnroot/bin/$cmd"
done
for cmd in sshfs ssh sshpass fusermount3; do copy_elf "$(command -v "$cmd")" "usr/bin/$cmd"; done
printf 'root:x:0:0:root:/root:/bin/sh\n' > "$lnroot/etc/passwd"
printf 'root:x:0:\n' > "$lnroot/etc/group"
printf 'hosts: files dns\npasswd: files\ngroup: files\n' > "$lnroot/etc/nsswitch.conf"
printf '127.0.0.1 localhost\n' > "$lnroot/etc/hosts"
kernel="$(basename "$(find /boot -name 'vmlinuz-*-generic' | sort -V | tail -1)" | sed 's/^vmlinuz-//')"
test -f "/boot/vmlinuz-$kernel"
for mod in virtio_pci virtio_net fuse qemu_fw_cfg; do
  while read -r module; do
    target="${module%.zst}"
    if [[ "$module" == *.zst ]]; then
      mkdir -p "$(dirname "$lnroot/$target")"
      zstd -dc "$module" > "$lnroot/$target"
    else
      install -D "$module" "$lnroot/$target"
    fi
  done < <(modprobe --set-version "$kernel" --show-depends "$mod" | awk '$1=="insmod" {print $2}')
done
mkdir -p "$lnroot/lib/modules/$kernel"
cp "/lib/modules/$kernel/modules.builtin"* "$lnroot/lib/modules/$kernel/"
depmod -b "$lnroot" "$kernel"
cat > "$lnroot/init" <<'EOF'
#!/bin/sh
export PATH=/bin:/usr/bin:/sbin
mount -t devtmpfs devtmpfs /dev
mount -t proc proc /proc
mount -t sysfs sysfs /sys
modprobe virtio_pci
modprobe virtio_net
modprobe fuse
modprobe qemu_fw_cfg
ip link set lo up
ip link set eth0 up
ip addr add 10.0.2.15/24 dev eth0
ip route add default via 10.0.2.2
job=/sys/firmware/qemu_fw_cfg/by_name/opt/workbench/job/raw
if [ -r "$job" ]; then
  cp "$job" /tmp/job
  /bin/sh /tmp/job
else
  /usr/bin/gnss-sdr --version
fi
echo "WORKBENCH_GUEST_EXIT=$?"
poweroff -f
EOF
chmod 755 "$lnroot/init"
sudo chroot "$lnroot" /usr/bin/gnss-sdr --version | tee guest-output/version.txt
sudo cp "/boot/vmlinuz-$kernel" guest-output/vmlinuz
sudo chmod 644 guest-output/vmlinuz
(cd "$lnroot" && find . -print0 | sort -z | cpio --null --quiet --owner=0:0 -o -H newc | gzip -1) > guest-output/initramfs.gz
git -C upstream archive --format=tar.gz -o "$PWD/guest-output/gnss-sdr-upstream.tar.gz" "$commit"
printf '%s\n' "$commit" > guest-output/upstream-commit.txt
dpkg-query -W -f='${Package}\t${Version}\n' > guest-output/build-packages.tsv
sha256sum "$exe" | awk '{print $1"  /usr/bin/gnss-sdr"}' > guest-output/receiver.sha256
dpkg-query -W -f='${Package}\t${Version}\t${source:Package}\t${source:Version}\n' > guest-output/source-packages.tsv
find /usr/share/doc -name copyright -type f -print0 | tar --null -T - -czf guest-output/package-notices.tar.gz
cp receiver-build/CMakeCache.txt guest-output/
(cd guest-output && sha256sum vmlinuz initramfs.gz gnss-sdr-upstream.tar.gz > SHA256SUMS)
