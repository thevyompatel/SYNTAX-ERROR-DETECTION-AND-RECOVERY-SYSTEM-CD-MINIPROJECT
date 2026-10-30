// Missing / wrong terminators -> Phrase-level recovery (insertion, substitution)
int main() {
    int a = 10
    int b = 20;
    int sum = a + b
    print(sum)
    for (int i = 0, i < 5, i++) {
        sum = sum + i
    }
    return 0
}
