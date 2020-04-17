# overlay-switch
This tool is useful when working with more versions of same software which requires to be installed in specific path. The tool enables user to switch versions without reinstalling the software. It is intended for developers and testers who need modify installed software, be able to switch between versions and be able to revert changes made previously. It allows to have more versions which are based on some common version and have some modification without need to copy all data.

## Basic idea
The idea behind this tool is to use overlayfs to help switching between software versions and allow user to do changes which can be easily discarded later. Basically all this script does is managing overlayfs and launching rsync. Additionally it does some checks to prevent user from doing something which does not make sense. Each version consists of it's own upper and lower directory which are combined using overlayfs. All lower directories are used when the version is based on an other version but only upper directory of last version is used. Data might be moved from upper directory to lower directory to become persistent or upper directory can be discarded.

## Installation
For the purpose of this guide I assume the software being managed is installed in paths **/opt/product1**, **/opt/product2** and so on. Also I assume this utility and storage of versions will be installed in **/opt/switch**.

- Install rsync package.

- Create installation directory and change the owner.
```
sudo mkdir /opt/switch
sudo chown `id -un`:`id -gn` /opt/switch
```

- Download the script from this repository and make it executable.
```
wget -O /opt/switch/switch.py https://raw.githubusercontent.com/jakub-vanik/overlay-switch/master/switch.py
chmod +x /opt/switch/switch.py
```

- Add following into **~/.bashrc** to set environment variables and create alias.
```
export SWITCH_PRODUCTS_ROOT=/opt
export SWITCH_STORAGE_ROOT=/opt/switch
alias switch=/opt/switch/switch.py
```

- Optionally create **/etc/sudoers.d/switch** with following content to allow mounting without password.
```
ALL ALL=(ALL) NOPASSWD: /usr/bin/mount -t overlay overlay -o * /opt/*
ALL ALL=(ALL) NOPASSWD: /usr/bin/umount /opt/*
ALL ALL=(ALL) NOPASSWD: /usr/bin/rmdir /opt/switch/*
```

## Usage
The utility has few commands to manage versions. In following description **product** means the name of directory inside **/opt** path where a software is installed.

- switch **create** [product] [version]

   creates new empty version of product, the directory /opt/[product] must exist

- switch **duplicate** [product] [new_version] [existing_version]

   creates new version by copying other version, only data from lower directory are copied

- switch **delete** [product] [version]

   deletes the version of product

- switch **derive** [product] [new_version] [existing_version]

   creates new version which uses lower directory of other version together with its own lower directory, does not copy data, otherwise behaves as duplication

- switch **detach** [product] [version]

   makes the version independent of parent version by copying parent's lower directory to own lower directory, derivation followed by detaching equals to duplication

- switch **select** [product] [version]

   makes the version accessible by mounting it to /opt/[prodact], all changes made by accessing files in /opt/[prodact] are stored in upper directory, if other version is already selected it is unselected first

- switch **unselect** [product]

   makes product inaccessible by unmounting /opt/[prodact] 

- switch **which** [product]

   prints currently selected version name

- switch **commit** [product] [version]

   applies changes accumulated in upper directory to lower directory, the version mustn't be selected, parent version is not affected when applied to derived version, commit is not allowed for the version which is parent of other version

- switch **undo** [product] [version]

   deletes changes in upper directory, the version mustn't be selected, parent version is not affected when applied to derived version

## Limitations
This works only in single user environment. Install all software and make all modifications as same user which runs the switch. Otherwise switch and rsync would not be able to access directories and files created by other user or root.
