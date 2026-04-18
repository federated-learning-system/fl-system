package minio

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

const (
	BucketModels  = "fl-models"
	BucketOffload = "fl-offload"

	PresignTTL = 10 * time.Minute
)

// Client wraps the MinIO Go SDK.
type Client struct {
	mc        *minio.Client
	presignMC *minio.Client // separate client for presigned URLs (public/external endpoint)
	log       *slog.Logger
}

// New creates a MinIO client.
// presignEndpoint is optional: when non-empty, presigned URLs are generated using
// that endpoint instead of the internal one (use for Docker/external client access).
func New(endpoint, accessKey, secretKey string, useSSL bool, log *slog.Logger, presignEndpoint ...string) (*Client, error) {
	mc, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, fmt.Errorf("minio client: %w", err)
	}
	c := &Client{mc: mc, log: log}
	if len(presignEndpoint) > 0 && presignEndpoint[0] != "" {
		pmc, err := minio.New(presignEndpoint[0], &minio.Options{
			Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
			Secure: false,
		})
		if err != nil {
			return nil, fmt.Errorf("minio presign client: %w", err)
		}
		c.presignMC = pmc
		log.Info("MinIO presigned URLs will use public endpoint", "endpoint", presignEndpoint[0])
	}
	return c, nil
}

// PresignedGetURL generates a presigned download URL for the given object.
// Uses the public endpoint client if configured.
func (c *Client) PresignedGetURL(ctx context.Context, bucket, key string) (string, error) {
	mc := c.mc
	if c.presignMC != nil {
		mc = c.presignMC
	}
	u, err := mc.PresignedGetObject(ctx, bucket, key, PresignTTL, nil)
	if err != nil {
		return "", fmt.Errorf("presign get %s/%s: %w", bucket, key, err)
	}
	return u.String(), nil
}

// PresignedPutURL generates a presigned upload URL.
// Uses the public endpoint client if configured.
func (c *Client) PresignedPutURL(ctx context.Context, bucket, key string) (string, error) {
	mc := c.mc
	if c.presignMC != nil {
		mc = c.presignMC
	}
	u, err := mc.PresignedPutObject(ctx, bucket, key, PresignTTL)
	if err != nil {
		return "", fmt.Errorf("presign put %s/%s: %w", bucket, key, err)
	}
	return u.String(), nil
}

// PutObject uploads data to MinIO.
func (c *Client) PutObject(ctx context.Context, bucket, key string, reader io.Reader, size int64, contentType string) error {
	_, err := c.mc.PutObject(ctx, bucket, key, reader, size, minio.PutObjectOptions{
		ContentType: contentType,
	})
	if err != nil {
		return fmt.Errorf("put %s/%s: %w", bucket, key, err)
	}
	return nil
}

// ObjectExists checks if an object exists in the bucket.
func (c *Client) ObjectExists(ctx context.Context, bucket, key string) (bool, error) {
	_, err := c.mc.StatObject(ctx, bucket, key, minio.StatObjectOptions{})
	if err != nil {
		errResp := minio.ToErrorResponse(err)
		if errResp.Code == "NoSuchKey" {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// ModelPresignedURL returns a presigned URL for the quantized ONNX model.
func (c *Client) ModelPresignedURL(ctx context.Context, version string) (string, error) {
	key := fmt.Sprintf("models/%s/model_quant.onnx", version)
	return c.PresignedGetURL(ctx, BucketModels, key)
}

// WeightsPresignedURL returns a presigned URL for the PyTorch weights checkpoint.
func (c *Client) WeightsPresignedURL(ctx context.Context, version string) (string, error) {
	key := fmt.Sprintf("models/%s/model_weights.pt", version)
	return c.PresignedGetURL(ctx, BucketModels, key)
}

// VocabPresignedURL returns a presigned URL for the vocabulary file.
func (c *Client) VocabPresignedURL(ctx context.Context) (string, error) {
	return c.PresignedGetURL(ctx, BucketModels, "vocab/vocab_8192.model")
}

// UpdateBlobKey returns the S3 key for a client's update blob.
func UpdateBlobKey(roundID, clientID string) string {
	return fmt.Sprintf("updates/%s/%s.delta.gz", roundID, clientID)
}
