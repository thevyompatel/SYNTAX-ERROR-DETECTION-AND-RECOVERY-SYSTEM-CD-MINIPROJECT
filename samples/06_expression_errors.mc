// Broken expressions -> Error productions + Panic mode
int main() {
    int a = 4;
    int b = 2;
    int c = a + * b;
    int d = a b;
    int e = (a + ) * 2;
    c = a * / b + 1;
    d = = 5;
    print("values", a, b, c);
    e = a - b;
    return 0;
}
