// A syntactically correct MiniC program - expected result: 0 errors
int factorial(int n) {
    int result = 1;
    for (int i = 1; i <= n; i++) {
        result = result * i;
    }
    return result;
}

int main() {
    int marks[5];
    float avg = 0.0;
    bool passed = true;
    int count = 0;

    while (count < 5) {
        marks[count] = count * 10 + 50;
        avg += marks[count];
        count++;
    }
    avg = avg / 5;

    if (avg >= 40 && passed) {
        print("Result: PASS", avg);
    } else {
        print("Result: FAIL");
    }
    print("5! =", factorial(5));
    return 0;
}
