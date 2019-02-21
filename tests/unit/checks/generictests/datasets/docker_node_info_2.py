# yapf: disable
checkname = "docker_node_info"

info = [[
    '{"ID": "XXXX:YYYY:6666","Containers":15,'
    '"ContainersRunning":6,"ContainersPaused":0,"ContainersStopped":9,"Images":7,'
    '"Driver":"overlay","DriverStatus":[["Backing', 'Filesystem","xfs"],["Supports',
    'd_type","true"]],"SystemStatus":null,"Plugins":{"Volume":["local"],'
    '"Network":["bridge","host"],"Authorization":null,'
    '"Log":["journald","json-file","splunk","syslog"]},"MemoryLimit":true,'
    '"SwapLimit":true,"KernelMemory":true,'
    '"SystemTime":"2000-01-01T01:00:00.000000000+01:00","LoggingDriver":"json-file",'
    '"CgroupDriver":"cgroupfs","NEventsListener":6,'
    '"KernelVersion":"3.10.0-666.6.6.el6.x86_64","OperatingSystem":"An', 'awesome',
    'one","OSType":"linux","Architecture":"x86_64",'
    '"IndexServerAddress":"https://index.docker.io/v1/",'
    '"RegistryConfig":{"AllowNondistributableArtifactsCIDRs":[],'
    '"AllowNondistributableArtifactsHostnames":[],"InsecureRegistryCIDRs":["127.0.0.0/8"],'
    '"IndexConfigs":{"docker.io":{"Name":"docker.io","Mirrors":[],"Secure":true,'
    '"Official":true}},"Mirrors":[]},"NCPU":4,"MemTotal":16666666666,'
    '"GenericResources":null,"DockerRootDir":"/data/docker",'
    '"HttpProxy":"http://proxy.foo:8080",'
    '"HttpsProxy":"http://proxy.foo:8080",'
    '"NoProxy":"localhost,', '127.0.0.0/8,', '66.666.66.666,', '.foo.bar,', '.gee.boo.it",',
    '"Name":"my_name","Labels":[],"ExperimentalBuild":false,"ServerVersion":"16.06.6-ce",'
    '"ClusterStore":"","ClusterAdvertise":"","Runtimes":{"runc":{"path":"docker-runc"}},'
    '"DefaultRuntime":"runc","Swarm":{"NodeID":"66666666666666",'
    '"NodeAddr":"66.666.66.666","LocalNodeState":"active","ControlAvailable":true,'
    '"Error":"","RemoteManagers":[{"NodeID":"6666666",'
    '"Addr":"66.666.66.666:6666"}],"Nodes":2,"Managers":1,'
    '"Cluster":{"ID":"cluster_id_66666666","Version":{"Index":66666666},'
    '"CreatedAt":"2016-06-06T06:56:56.66666666Z",'
    '"UpdatedAt":"2016-12-06T06:56:56.66666666Z","Spec":{"Name":"default","Labels":{},'
    '"Orchestration":{"TaskHistoryRetentionLimit":5},"Raft":{"SnapshotInterval":10000,'
    '"KeepOldSnapshots":0,"LogEntriesForSlowFollowers":500,"ElectionTick":10,'
    '"HeartbeatTick":1},"Dispatcher":{"HeartbeatPeriod":6000000000},'
    '"CAConfig":{"NodeCertExpiry":6666666666666666},"TaskDefaults":{},'
    '"EncryptionConfig":{"AutoLockManagers":false}},"TLSInfo":{"TrustRoot":'
    '"-----BEGIN', 'CERTIFICATE-----\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoob\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoob\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoob\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoob\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoob\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoob\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoobarFoob\n'
    'FoobarFoobarFoobarFoobarFoobarFoobarFoobar==\n'
    '-----END', 'CERTIFICATE-----\n",'
    '"CertIssuerSubject":"Jim",'
    '"CertIssuerPublicKey":"odoriuhaoerhaergjhargjkhaejfgasdg=="},'
    '"RootRotationInProgress":false}},"LiveRestoreEnabled":false,"Isolation":"",'
    '"InitBinary":"docker-init","ContainerdCommit":'
    '{"ID":"666666666666666666666666666666666666",'
    '"Expected":"77777777777777777777777777777777777777777"},'
    '"RuncCommit":{"ID":"444444444444444444444444444444444444444",'
    '"Expected":"ffffffffffffffffffffffffffffffffffffffffffffff"},'
    '"InitCommit":{"ID":"9999999","Expected":"6666666"},'
    '"SecurityOptions":["name=seccomp,profile=default"]}'
]]
