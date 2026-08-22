use std::io;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;

pub(crate) enum ReadFrameError {
    Io,
    TooLarge,
}

pub(crate) async fn read_frame<R>(reader: &mut R, max_bytes: u32) -> Result<Vec<u8>, ReadFrameError>
where
    R: AsyncRead + Unpin,
{
    let length = reader.read_u32().await.map_err(|_| ReadFrameError::Io)?;
    if length > max_bytes {
        return Err(ReadFrameError::TooLarge);
    }
    let body_len = usize::try_from(length).map_err(|_| ReadFrameError::TooLarge)?;
    let mut body = vec![0; body_len];
    reader
        .read_exact(&mut body)
        .await
        .map_err(|_| ReadFrameError::Io)?;
    Ok(body)
}

pub(crate) async fn write_frame<W>(writer: &mut W, body: &[u8]) -> io::Result<()>
where
    W: AsyncWrite + Unpin,
{
    let length = u32::try_from(body.len())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "frame too large"))?;
    writer.write_u32(length).await?;
    writer.write_all(body).await?;
    writer.flush().await
}
