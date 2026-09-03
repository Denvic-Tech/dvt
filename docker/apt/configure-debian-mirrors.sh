#!/bin/sh
set -eu

mirror_dir=/etc/apt/mirrors
mkdir -p "$mirror_dir"

cat > "$mirror_dir/debian.list" <<'EOF'
http://deb.debian.org/debian/	priority:1
http://mirror.yandex.ru/debian/	priority:2
EOF

cat > "$mirror_dir/debian-security.list" <<'EOF'
http://deb.debian.org/debian-security/	priority:1
http://mirror.yandex.ru/debian-security/	priority:2
EOF

rewrite_sources() {
    sources_file="$1"
    sed -i \
        -e 's#http://deb.debian.org/debian-security#mirror+file:/etc/apt/mirrors/debian-security.list#g' \
        -e 's#https://deb.debian.org/debian-security#mirror+file:/etc/apt/mirrors/debian-security.list#g' \
        -e 's#http://deb.debian.org/debian#mirror+file:/etc/apt/mirrors/debian.list#g' \
        -e 's#https://deb.debian.org/debian#mirror+file:/etc/apt/mirrors/debian.list#g' \
        "$sources_file"
}

for sources_file in \
    /etc/apt/sources.list \
    /etc/apt/sources.list.d/*.list \
    /etc/apt/sources.list.d/*.sources
do
    [ -f "$sources_file" ] || continue
    rewrite_sources "$sources_file"
done
