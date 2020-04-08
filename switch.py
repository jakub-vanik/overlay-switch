#!/usr/bin/python3

import os
import re
import shutil
import subprocess
import sys


def load_environment():
  global products_root, storage_root
  try:
    products_root = os.environ["SWITCH_PRODUCTS_ROOT"].rstrip("/")
    storage_root = os.environ["SWITCH_STORAGE_ROOT"].rstrip("/")
  except KeyError:
    raise Exception("environment variables not set")


def is_sub_path(sub_path, path):
  while sub_path:
    if sub_path == path:
      return True
    sub_path, name = os.path.split(sub_path)
    if not name:
      return False
  return False


def check_roots():
  if is_sub_path(products_root, storage_root):
    raise Exception("products root colides with storage")


def get_argument(index):
  if len(sys.argv) > index:
    return sys.argv[index]
  else:
    raise Exception("not enough arguments")


def check_product(product):
  product_path = os.path.join(products_root, product)
  if is_sub_path(product_path, storage_root):
    raise Exception("product colides with storage")
  if not os.path.isdir(product_path):
    raise Exception("product not found")
  product_path = os.path.join(storage_root, product)
  if not os.path.isdir(product_path):
    os.makedirs(product_path)


def version_exists(product, version):
  return os.path.isdir(os.path.join(storage_root, product, version))


def extract_path(path):
  path, name = os.path.split(path)
  if name != "lower" and name != "upper":
    raise Exception("unexpected path")
  path, version = os.path.split(path)
  path, product = os.path.split(path)
  if path != storage_root:
    raise Exception("unexpected path")
  return product, version


def read_mounts():
  mounts = []
  regex = re.compile("^overlay on (.*) type overlay \(.*,lowerdir=([^,]*),upperdir=([^,]*),.*\)$")
  process = subprocess.Popen(["mount"], stdout=subprocess.PIPE)
  for buff in process.stdout:
    line = buff.decode("utf-8").strip()
    result = regex.search(line)
    if result:
      mount_point = result.group(1)
      base, product = os.path.split(mount_point)
      if base == products_root:
        upper_path = result.group(3)
        upper_product, upper_version = extract_path(upper_path)
        if upper_product != product:
          raise Exception("unexpected mount")
        lower_versions = []
        for lower_path in result.group(2).split(":")[:-1]:
          lower_product, lower_version = extract_path(lower_path)
          if lower_product != product:
            raise Exception("unexpected mount")
          lower_versions.append(lower_version)
        if lower_versions[0] != upper_version:
          raise Exception("unexpected mount")
        mounts.append((product, upper_version, lower_versions))
  return mounts


def is_product_used(product):
  return any(m[0] == product for m in read_mounts())


def is_version_used(product, version):
  return any(m[0] == product and version in m[2] for m in read_mounts())


def read_parent(product, version):
  path = os.path.join(storage_root, product, version, "parent")
  if not os.path.isfile(path):
    return None
  with open(path, "r") as file:
    return file.read()


def write_parent(product, version, parent):
  path = os.path.join(storage_root, product, version, "parent")
  if parent:
    with open(path, "w") as file:
      file.write(parent)
  else:
    if os.path.isfile(path):
      os.remove(path)


def read_parents(product, version):
  parent = read_parent(product, version)
  if parent:
    return [version] + read_parents(product, parent)
  else:
    return [version]


def is_parent(product, version):
  product_path = os.path.join(storage_root, product)
  for name in os.listdir(product_path):
    if not name.startswith("."):
      if os.path.isdir(os.path.join(product_path, name)):
        if read_parent(product, name) == version:
          return True
  return False


def create_workdir(path):
  if os.path.isdir(path):
    remove_workdir(path)
  os.makedirs(path)


def remove_workdir(path):
  for name in os.listdir(path):
    inner_path = os.path.join(path, name)
    if os.path.isdir(inner_path):
      subprocess.run(["sudo", "rmdir", inner_path], check=True)
  os.rmdir(path)


def mount_overlay(mount_path, work_path, product, version, lower_only=False, write_lower=False):
  create_workdir(work_path)
  product_path = os.path.join(storage_root, product)
  empty_path = os.path.join(product_path, ".empty")
  os.makedirs(empty_path, exist_ok=True)
  lower_paths = [os.path.join(product_path, parent, "lower")
                 for parent in read_parents(product, version)] + [empty_path]
  version_path = os.path.join(product_path, version)
  upper_path = os.path.join(version_path, "upper")
  if write_lower:
    upper_path = lower_paths[0]
    lower_paths = lower_paths[1:]
  if lower_only:
    mount_options = "lowerdir=" + ":".join(lower_paths) + ",workdir=" + work_path
  else:
    mount_options = "lowerdir=" + ":".join(lower_paths) + \
        ",upperdir=" + upper_path + ",workdir=" + work_path
  subprocess.run(["sudo", "mount", "-t", "overlay", "overlay",
                  "-o", mount_options, mount_path], check=True)


def umount_overlay(mount_path, work_path):
  subprocess.run(["sudo", "umount", mount_path], check=True)
  remove_workdir(work_path)


def rsync(source_path, destination_path, merge=False):
  subprocess.run(["rsync", "-r", "-l", "-p", "-E", "-X", "-o", "-g", "-t", "--delete",
                  "--progress", source_path + "/", destination_path], check=True)


def recreate_empty(path):
  shutil.rmtree(path)
  os.makedirs(path)


def create(product, version):
  if version_exists(product, version):
    raise Exception("version already exists")
  version_path = os.path.join(storage_root, product, version)
  os.makedirs(version_path)
  os.makedirs(os.path.join(version_path, "lower"))
  os.makedirs(os.path.join(version_path, "upper"))


def duplicate(product, version, parent):
  if not version_exists(product, parent):
    raise Exception("parent does not exist")
  create(product, version)
  write_parent(product, version, read_parent(product, parent))
  version_path = os.path.join(storage_root, product, version)
  src_work_path = os.path.join(version_path, ".src_work")
  src_mount_path = os.path.join(version_path, ".src_mount")
  dst_work_path = os.path.join(version_path, ".dst_work")
  dst_mount_path = os.path.join(version_path, ".dst_mount")
  os.makedirs(src_mount_path, exist_ok=True)
  os.makedirs(dst_mount_path, exist_ok=True)
  mount_overlay(src_mount_path, src_work_path, product, parent, lower_only=True)
  mount_overlay(dst_mount_path, dst_work_path, product, version, write_lower=True)
  try:
    rsync(src_mount_path, dst_mount_path)
  finally:
    umount_overlay(src_mount_path, src_work_path)
    umount_overlay(dst_mount_path, dst_work_path)
    os.rmdir(src_mount_path)
    os.rmdir(dst_mount_path)


def delete(product, version):
  if not version_exists(product, version):
    raise Exception("version does not exist")
  if is_version_used(product, version):
    raise Exception("version is in use, unselect first")
  if is_parent(product, version):
    raise Exception("version is parent, detach first")
  shutil.rmtree(os.path.join(storage_root, product, version))


def derive(product, version, parent):
  if not version_exists(product, parent):
    raise Exception("parent does not exist")
  create(product, version)
  write_parent(product, version, parent)


def detach(product, version):
  if not version_exists(product, version):
    raise Exception("version does not exist")
  if is_version_used(product, version):
    raise Exception("version is in use, unselect first")
  if not read_parent(product, version):
    raise Exception("version does not have parent")
  version_path = os.path.join(storage_root, product, version)
  new_lower_path = os.path.join(version_path, ".new_lower")
  if os.path.isdir(new_lower_path):
    shutil.rmtree(new_lower_path)
  os.mkdir(new_lower_path)
  src_work_path = os.path.join(version_path, ".src_work")
  src_mount_path = os.path.join(version_path, ".src_mount")
  os.makedirs(src_mount_path, exist_ok=True)
  mount_overlay(src_mount_path, src_work_path, product, version, lower_only=True)
  try:
    rsync(src_mount_path, new_lower_path)
  finally:
    umount_overlay(src_mount_path, src_work_path)
    os.rmdir(src_mount_path)
  lower_path = os.path.join(version_path, "lower")
  shutil.rmtree(lower_path)
  shutil.move(new_lower_path, lower_path)
  write_parent(product, version, None)


def select(product, version):
  if not version_exists(product, version):
    raise Exception("version does not exist")
  if is_product_used(product):
    unselect(product)
  mount_path = os.path.join(products_root, product)
  product_path = os.path.join(storage_root, product)
  work_path = os.path.join(product_path, ".work")
  mount_overlay(mount_path, work_path, product, version)


def unselect(product):
  if not is_product_used(product):
    raise Exception("no version is selected")
  mount_path = os.path.join(products_root, product)
  work_path = os.path.join(storage_root, product, ".work")
  umount_overlay(mount_path, work_path)


def which(product):
  for mount in read_mounts():
    if mount[0] == product:
      print(mount[1])


def commit(product, version):
  if not version_exists(product, version):
    raise Exception("version does not exist")
  if is_version_used(product, version):
    raise Exception("version is in use, unselect first")
  if is_parent(product, version):
    raise Exception("version is parent, detach first")
  version_path = os.path.join(storage_root, product, version)
  src_work_path = os.path.join(version_path, ".src_work")
  src_mount_path = os.path.join(version_path, ".src_mount")
  dst_work_path = os.path.join(version_path, ".dst_work")
  dst_mount_path = os.path.join(version_path, ".dst_mount")
  os.makedirs(src_mount_path, exist_ok=True)
  os.makedirs(dst_mount_path, exist_ok=True)
  mount_overlay(src_mount_path, src_work_path, product, version)
  mount_overlay(dst_mount_path, dst_work_path, product, version, write_lower=True)
  try:
    rsync(src_mount_path, dst_mount_path)
  finally:
    umount_overlay(src_mount_path, src_work_path)
    umount_overlay(dst_mount_path, dst_work_path)
    os.rmdir(src_mount_path)
    os.rmdir(dst_mount_path)
  upper_path = os.path.join(version_path, "upper")
  recreate_empty(upper_path)


def undo(product, version):
  if not version_exists(product, version):
    raise Exception("version does not exist")
  if is_version_used(product, version):
    raise Exception("version is in use, unselect first")
  version_path = os.path.join(storage_root, product, version)
  upper_path = os.path.join(version_path, "upper")
  recreate_empty(upper_path)


def main():
  try:
    load_environment()
    check_roots()
    command = get_argument(1)
    if command == "create":
      product = get_argument(2)
      version = get_argument(3)
      check_product(product)
      create(product, version)
      return
    if command == "duplicate":
      product = get_argument(2)
      version = get_argument(3)
      parent = get_argument(4)
      check_product(product)
      duplicate(product, version, parent)
      return
    if command == "delete":
      product = get_argument(2)
      version = get_argument(3)
      check_product(product)
      delete(product, version)
      return
    if command == "derive":
      product = get_argument(2)
      version = get_argument(3)
      parent = get_argument(4)
      check_product(product)
      derive(product, version, parent)
      return
    if command == "detach":
      product = get_argument(2)
      version = get_argument(3)
      check_product(product)
      detach(product, version)
      return
    if command == "select":
      product = get_argument(2)
      version = get_argument(3)
      check_product(product)
      select(product, version)
      return
    if command == "unselect":
      product = get_argument(2)
      check_product(product)
      unselect(product)
      return
    if command == "which":
      product = get_argument(2)
      check_product(product)
      which(product)
      return
    if command == "commit":
      product = get_argument(2)
      version = get_argument(3)
      check_product(product)
      commit(product, version)
      return
    if command == "undo":
      product = get_argument(2)
      version = get_argument(3)
      check_product(product)
      undo(product, version)
      return
    raise Exception("unknown command")
  except Exception as e:
    print("Error: " + str(e))


if __name__ == "__main__":
  main()
