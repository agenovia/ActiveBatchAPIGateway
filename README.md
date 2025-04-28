 TODO

## Terminology

Service Account:
    The service account is an user authorized to read and/or perform operations on ActiveBatch.
    If the user account used to authenticate is only allowed to *READ* objects, then the request may only access **GET** operations.

    Hypothetical Example: HPSJ\ActiveBatchRestAPISVC is an administrator. If HPSJ\ActiveBatchRestAPISVC username and password are provided, then the gateway will authenticate and operate as the user HPSJ\ActiveBatchRestAPISVC.

ActiveBatch REST Server:
    This is the **URL** of the target REST server.

ActiveBatch JSS Server:
    This is the **FQDN or the IP address** of the target Job Scheduler Server.
