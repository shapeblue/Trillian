param(
[String] $vchost,
[String] $vcuser,
[String] $vcpass,
[String] $esxihosts,
[String] $dvswitchname
)

# Stop spam
Set-PowerCLIConfiguration -Scope User -ParticipateInCEIP $false

# Ignore certs
Set-PowerCLIConfiguration -InvalidCertificateAction ignore -confirm:$false

# VC connectivity
Write-Host "Connecting to VC host " $vchost
Connect-VIServer -Server $vchost -User $vcuser -Pass $vcpass

# Array of esxi hosts
$esxihostarray = $esxihosts -split ','
foreach ($esxihost in $esxihostarray) {
$dvswitch = Get-VDSwitch $dvswitchname

# Add ESXi host to dvSwitch
Write-Host "Adding" $esxihost "to" $dvswitchname
Add-VDSwitchVMHost -VMHost $esxihost -VDSwitch $dvswitch
$management_vmkernel = Get-VMHostNetworkAdapter -VMHost $esxihost -Name "vmk0"
$management_vmkernel_portgroup = Get-VDPortgroup -name "Management Network" -VDSwitch $dvswitchname

# Migration esxi host networking to dvSwitch
Write-Host "Adding vmnic0 to" $dvswitchname
$esxihostnic = Get-VMHost $esxihost | Get-VMHostNetworkAdapter -Physical -Name vmnic0
Add-VDSwitchPhysicalNetworkAdapter -VMHostPhysicalNic $esxihostnic -DistributedSwitch $dvswitch -VMHostVirtualNic $management_vmkernel -VirtualNicPortgroup $management_vmkernel_portgroup -Confirm:$false
}
Disconnect-VIServer -Server $global:DefaultVIServers -Force -Confirm:$false
