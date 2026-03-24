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
	mc  *minio.Client
	log *slog.Logger
}

// New creates a MinIO client.
func New(endpoint, accessKey, secretKey string, useSSL bool, log *slog.Logger) (*Client, error) {
	mc, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, fmt.Errorf("minio client: %w", err)
	}
	return &Client{mc: mc, log: log}, nil
}

// PresignedGetURL generates a presigned download URL for the given object.
func (c *Client) PresignedGetURL(ctx context.Context, bucket, key string) (string, error) {
	u, err := c.mc.PresignedGetObject(ctx, bucket, key, PresignTTL, nil)
	if err != nil {
		return "", fmt.Errorf("presign get %s/%s: %w", bucket, key, err)
	}
	return u.String(), nil
}

// PresignedPutURL generates a presigned upload URL.
func (c *Client) PresignedPutURL(ctx context.Context, bucket, key string) (string, error) {
	u, err := c.mc.PresignedPutObject(ctx, bucket, key, PresignTTL)
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

// VocabPresignedURL returns a presigned URL for the vocabulary file.
func (c *Client) VocabPresignedURL(ctx context.Context) (string, error) {
	return c.PresignedGetURL(ctx, BucketModels, "vocab/vocab_8192.model")
}

// UpdateBlobKey returns the S3 key for a client's update blob.
func UpdateBlobKey(roundID, clientID string) string {
	return fmt.Sprintf("updates/%s/%s.delta.gz", roundID, clientID)
}
