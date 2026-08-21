#!/usr/bin/env python3
# _*_ coding:utf-8 _*_

import os
import json
import hashlib
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import traceback
import urllib.request
from string import Template

parent_path = os.path.dirname(os.path.realpath(__file__))

def md5sum(full_path):
    with open(full_path, 'rb') as rf:
        return hashlib.md5(rf.read()).hexdigest()

def sha256sum(full_path):
    with open(full_path, 'rb') as rf:
        return hashlib.sha256(rf.read()).hexdigest()

def download_file(url, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".download-", dir=dest_dir)
    try:
        with os.fdopen(fd, "wb") as tmp:
            with urllib.request.urlopen(url, timeout=60) as response:
                shutil.copyfileobj(response, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        return tmp_path
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise

def extract_binary_from_archive(archive_path, module, binary_name, dest_dir):
    candidates = {
        binary_name,
        f"./{binary_name}",
        f"bin/{binary_name}",
        f"./bin/{binary_name}",
        f"{module}/bin/{binary_name}",
        f"./{module}/bin/{binary_name}",
    }
    with tarfile.open(archive_path, "r:*") as tf:
        member = None
        for item in tf.getmembers():
            name = item.name.lstrip("/")
            if name in candidates:
                member = item
                break
        if member is None:
            raise Exception(f"archive does not contain {binary_name}")
        if not member.isfile():
            raise Exception(f"archive member is not a file: {member.name}")
        source = tf.extractfile(member)
        if source is None:
            raise Exception(f"cannot extract archive member: {member.name}")
        fd, tmp_path = tempfile.mkstemp(prefix=".extract-", dir=dest_dir)
        try:
            with os.fdopen(fd, "wb") as tmp:
                shutil.copyfileobj(source, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
            return tmp_path
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

def prepare_downloaded_binary(downloaded_path, module, binary_name, dest_dir):
    if not tarfile.is_tarfile(downloaded_path):
        return downloaded_path
    extracted_path = extract_binary_from_archive(downloaded_path, module, binary_name, dest_dir)
    os.unlink(downloaded_path)
    return extracted_path

def apply_binary_url(conf, module_path):
    binary_url = str(conf.get("binary_url", "")).strip()
    if not binary_url:
        return

    binary_sha256 = str(conf.get("binary_sha256", "")).strip()
    binary_name = str(conf.get("binary_name", "")).strip()
    if not binary_sha256:
        raise Exception("binary_sha256 is required when binary_url is set")
    if not binary_name:
        raise Exception("binary_name is required when binary_url is set")

    bin_dir = os.path.join(module_path, "bin")
    binary_path = os.path.join(bin_dir, binary_name)
    downloaded_path = download_file(binary_url, bin_dir)
    try:
        actual_sha256 = sha256sum(downloaded_path)
        if actual_sha256.lower() != binary_sha256.lower():
            raise Exception(f"sha256 mismatch for {binary_url}: expected {binary_sha256}, got {actual_sha256}")
        ready_path = prepare_downloaded_binary(downloaded_path, conf["module"], binary_name, bin_dir)
        os.replace(ready_path, binary_path)
    except Exception:
        try:
            os.unlink(downloaded_path)
        except FileNotFoundError:
            pass
        raise

    current = os.stat(binary_path).st_mode
    os.chmod(binary_path, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

def get_or_create():
    conf_path = os.path.join(parent_path, "config.json.js")
    conf = {}
    if not os.path.isfile(conf_path):
        print("config.json.js not found, build.py is root path. auto write config.json.js")
        module_name = os.path.basename(parent_path)
        conf["module"] = module_name
        conf["version"] = "0.0.1"
        conf["home_url"] = f"Module_{module_name}.asp"
        conf["title"] = f"title of {module_name}"
        conf["description"] = f"description of {module_name}"
    else:
        with open(conf_path, "r", encoding="utf-8") as fc:
            content = fc.read()
            try:
                conf = json.loads(content)
            except json.JSONDecodeError:
                conf = json.loads(re.sub(r",\s*([}\]])", r"\1", content))
    return conf

def has_install_script(module_path):
    for name in os.listdir(module_path):
        if name == "install.sh":
            return True
        if name.endswith(".sh") and (name.startswith("install_") or name.startswith("install-")):
            return True
    return False

def build_module():
    try:
        conf = get_or_create()
    except Exception as e:
        print("config.json.js file format is incorrect")
        traceback.print_exc()
        return 1

    if "module" not in conf:
        conf["module"] = os.path.basename(parent_path)

    module_path = os.path.join(parent_path, conf["module"])
    if not os.path.isdir(module_path):
        print(f"not found {module_path} dir, check config.json.js is module?")
        return 1

    if not has_install_script(module_path):
        print(f"not found install script in {module_path}, check install.sh file")
        return 1

    try:
        apply_binary_url(conf, module_path)
    except Exception:
        print("failed to prepare binary_url")
        traceback.print_exc()
        return 1

    print("build...")
    t = Template("cd $parent_path && rm -f $module.tar.gz && tar -zcf $module.tar.gz $module")
    os.system(t.substitute({"parent_path": parent_path, "module": conf["module"]}))
    
    conf["md5"] = md5sum(os.path.join(parent_path, f"{conf['module']}.tar.gz"))
    conf_path = os.path.join(parent_path, "config.json.js")
    
    with open(conf_path, "w", encoding="utf-8") as fw:
        json.dump(conf, fw, sort_keys=True, indent=4, ensure_ascii=False)

    print("build done", f"{conf['module']}.tar.gz")
    # hook_path = os.path.join(parent_path, "backup.sh")
    # if os.path.isfile(hook_path):
    #     os.system(hook_path)

    return 0

sys.exit(build_module())
