# ansible-proserver-mail

Mail role for Proserver

## Supported Operating Systems

- FreeBSD [Proserver](https://infrastructure.punkt.de/de/produkte/proserver.html)

## Role Arguments


An Ansible role that sets up mail configuration on a Proserver.

#### Options for `mail`

|Option|Description|Type|Required|Default|
|---|---|---|---|---|
| `enable_mta` | Enables or disables the Mail Transfer Agent (MTA). | bool | no | True |
| `aliases` | Dictionary of email aliases. | dict | no | {} |

## Dependencies

None.

## Installation
Add this role to the requirements.yml of your playbook as follows:
```yaml
roles:
  - name: ansible-proserver-mail
    src: https://github.com/punktDe/ansible-proserver-mail
```

Afterwards, install the role by running `ansible-galaxy install -r requirements.yml`

## Example Playbook

```yaml
- hosts: all
  roles:
    - name: ansible-proserver-mail
```
