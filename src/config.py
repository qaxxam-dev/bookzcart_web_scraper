from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    OPENROUTER_API_KEY: str
    DEEPINFRA_API_KEY: str
    DATABASE: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    PORT: int
    DATABASE_NAME: str

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"{self.DATABASE}+asyncpg://{self.DATABASE_USER}:"
            f"{self.DATABASE_PASSWORD}@localhost:{self.PORT}/"
            f"{self.DATABASE_NAME}"
        )

    GENAI_API_KEY_01: str = "AQ.Ab8RN6LWbe1PiNbbpjmw-iqFWfoISbP8CPVpI2L2wjjgkdb_5A"
    GENAI_API_KEY_02: str = "AIzaSyCbtV1EBn67m6QcUwdtxETKEfRz2gu9oyQ"
    GENAI_API_KEY_03: str = "AQ.Ab8RN6JMROVb1gNawpg7HLLKZ-BNSy7DJz5HaiPpl2ahVMb1rg"
    GENAI_API_KEY_04: str = "AQ.Ab8RN6IM-vUtfkjeBV0IwGQyn5Sc55jbOjjhDloYQcCO7Pm3uA"
    GENAI_API_KEY_05: str = "AIzaSyBeEXtrt1qXaah9j0jggNDbKr14UvCBU-Q"
    GENAI_API_KEY_06: str = "AQ.Ab8RN6I_a1afa1vCMaSpxmK20DvxhnHZz16OpUUoDJLpaxvh7A"
    GENAI_API_KEY_07: str = "AQ.Ab8RN6JdXCYlMhptw9z5sKG1r3180bGLlllerDaeEStmFFG0ew"
    GENAI_API_KEY_08: str = "AIzaSyDYKSy7wdQmjDa7wXFM5xJ_cSrTDH24cl0"
    GENAI_API_KEY_09: str = "AIzaSyCv8ri4x_bfCZZ6y_PaxwjyRtyLT9K2f7c"


settings = Settings()
