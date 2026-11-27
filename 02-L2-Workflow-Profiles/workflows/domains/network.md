# Network And Identity Domain

Route through `security-orchestrator`, then use `network-pentest` in staged
sequence:

1. Host, port, and protocol inventory (`network.scan`).
2. Directory, SMB/LDAP/Kerberos, and ADCS enumeration plus attack-path graph
   collection (`network.ad`: Impacket, BloodHound, Certipy, Kerbrute).
3. Single-threaded, lockout-aware credential validation strictly below account
   lockout thresholds; never fan out password sprays.
4. Authorized segmentation or tunnel verification (`network.pivot`: Chisel SOCKS)
   strictly inside approved ROE targets. Never expand unapproved subnets,
   deploy persistence implants, or run destructive DC actions without explicit
   written approval.

Record source address, target CIDR/host set, identity context, rate limits, and
time window before active scanning. Save inventories under `artifacts/network/`,
reusable commands under `scripts/`, and before/after evidence for every lead.
