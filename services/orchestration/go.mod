module github.com/x9z0/fls/orchestration

go 1.23

require (
	github.com/x9z0/fls/proto v0.0.0
	google.golang.org/grpc v1.64.0
	google.golang.org/protobuf v1.34.2
)

replace github.com/x9z0/fls/proto => ../../proto/aggregationv1
